/*
 * TensorFlow Lite Micro inference backend for the collar's confidence-gated cascade.
 *
 * DESIGN , RUNTIME MODELS, NO MODEL COMPILED IN
 * ----------------------------------------------
 * classifier.c declares four WEAK hooks (clf_imu_model_present / clf_audio_model_present /
 * imu_model_infer / audio_model_infer). This file provides the STRONG extern "C" definitions that
 * override them at link time, wiring the cascade to TFLite-Micro. Their signatures match the weak
 * ones EXACTLY (including C linkage) so the linker picks these.
 *
 * There is deliberately no model baked into the firmware. Instead each stage owns a "slot"
 * (ModelSlot) holding a model pointer+len, a MicroMutableOpResolver, a MicroInterpreter and a
 * static tensor arena. A slot is empty at boot:
 *
 *     present() == false  ->  the weak-overriding *_model_present() returns false
 *                          ->  the cascade in classifier.c never calls the infer hook for that stage
 *                          ->  the firmware runs MODEL-FREE and clf_classify() yields CLF_UNKNOWN.
 *
 * A model is installed at runtime via model_loader.h (clf_set_imu_model / clf_set_audio_model),
 * intended for a Phase-3 OTA push. present() flips to true only after a model buffer is set AND
 * AllocateTensors() succeeds. If the arena is too small AllocateTensors() fails and present() stays
 * false , the firmware simply keeps running model-free rather than crashing.
 *
 * INPUT TRANSFORM , MUST MIRROR TRAINING
 * --------------------------------------
 * The pre-processing here mirrors the training pipeline: per window, per channel, subtract the mean
 * over the TIME axis, then divide by (global max-abs over the whole window + 1e-6). To save RAM this
 * is computed by streaming DIRECTLY from the int16 source samples and quantizing straight into the
 * int8 input tensor (with the tensor's OWN scale/zero_point); no intermediate float window buffer is
 * materialized. The most-recent samples are conceptually right-aligned into the model window with
 * leading zeros (front zero-pad), and those zero-pad positions are counted in the per-window
 * normalization exactly as the trainer's padded window does. For the audio stage the pcm handed in is
 * already 8 kHz µ-law-round-tripped by audio_to_model_pcm() (audio_codec.h), so the representation
 * matches training before this normalization runs.
 *
 * Op set and arena sizes are first guesses , see comments at MODEL slots / resolver below; both MUST
 * be tuned against the real exported models on hardware.
 */

#include <cmath>
#include <cstdint>
#include <cstring>
#include <new>   /* placement new for the interpreter storage */

#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"

extern "C" {
#include "classifier.h"
#include "model_loader.h"
#include "imu.h"
#include "audio_codec.h"
}

namespace {

/* Window geometry , must match how the models were trained. */
constexpr int kImuFrames   = IMU_RATE_HZ;        /* 104 most-recent IMU frames                */
constexpr int kImuChannels = IMU_AXES;           /* 6 interleaved axes [ax,ay,az,gx,gy,gz]    */
constexpr int kImuWindow   = kImuFrames * kImuChannels;

constexpr int kAudioSamples  = MODEL_AUDIO_RATE_HZ; /* 8000 most-recent 8 kHz samples         */
constexpr int kAudioChannels = 1;
constexpr int kAudioWindow   = kAudioSamples * kAudioChannels;

/*
 * Tensor arenas. Static (no heap on this firmware). These are STARTING POINTS and MUST be tuned to
 * the real exported models on hardware: if a model needs more than its arena, AllocateTensors() in
 * the setter fails and that slot's present() simply stays false (firmware runs model-free).
 */
constexpr size_t kImuArenaBytes   = 16 * 1024;   /* IMU model: small temporal conv net        */
constexpr size_t kAudioArenaBytes = 48 * 1024;   /* audio model: larger 1-D conv over 8000 pts */

alignas(16) uint8_t g_imu_arena[kImuArenaBytes];
alignas(16) uint8_t g_audio_arena[kAudioArenaBytes];

/*
 * The op resolver set. These cover a typical quantized temporal/spectral conv classifier. The set
 * MAY NEED ADJUSTING once the real model is exported , if Invoke()/AllocateTensors reports a missing
 * op, add it here (and bump the template count). 16 ops registered below , the EXPAND_DIMS/SQUEEZE
 * (+ shape ops) are what Keras Conv1D lowers to, confirmed needed on real hardware.
 */
using MeowOpResolver = tflite::MicroMutableOpResolver<16>;

bool BuildResolver(MeowOpResolver &r)
{
	if (r.AddConv2D()          != kTfLiteOk) return false;
	if (r.AddDepthwiseConv2D() != kTfLiteOk) return false;
	if (r.AddMaxPool2D()       != kTfLiteOk) return false;
	if (r.AddAveragePool2D()   != kTfLiteOk) return false;
	if (r.AddFullyConnected()  != kTfLiteOk) return false;
	if (r.AddReshape()         != kTfLiteOk) return false;
	if (r.AddSoftmax()         != kTfLiteOk) return false;
	if (r.AddRelu()            != kTfLiteOk) return false;
	if (r.AddMean()            != kTfLiteOk) return false;
	if (r.AddQuantize()        != kTfLiteOk) return false;
	if (r.AddDequantize()      != kTfLiteOk) return false;
	/* Keras Conv1D lowers to CONV_2D wrapped in EXPAND_DIMS / SQUEEZE (the converter can also emit
	 * shape ops); real hardware reported "Didn't find op for builtin opcode 'EXPAND_DIMS'". */
	if (r.AddExpandDims()      != kTfLiteOk) return false;
	if (r.AddSqueeze()         != kTfLiteOk) return false;
	if (r.AddStridedSlice()    != kTfLiteOk) return false;
	if (r.AddPack()            != kTfLiteOk) return false;
	if (r.AddShape()           != kTfLiteOk) return false;
	return true;
}

/*
 * One inference stage. Empty until a model is set + tensors allocated; present_ gates everything.
 * The MicroInterpreter / resolver are stored in raw storage and placement-new'd on each load so a
 * slot can be re-armed with a new model (OTA replace) without dynamic allocation.
 */
class ModelSlot {
public:
	ModelSlot(uint8_t *arena, size_t arena_bytes)
	    : arena_(arena), arena_bytes_(arena_bytes) {}

	bool present() const { return present_; }

	/* (Re)build the interpreter on buf/len and allocate tensors. Returns success; on any failure the
	 * slot is left not-present and the firmware keeps running model-free. */
	bool Load(const uint8_t *buf, size_t len)
	{
		present_ = false;
		interpreter_ = nullptr;
		if (buf == nullptr || len == 0) {
			return false;
		}

		const tflite::Model *model = tflite::GetModel(buf);
		if (model == nullptr || model->version() != TFLITE_SCHEMA_VERSION) {
			return false;
		}

		/* The op set is fixed and identical across reloads, so build the resolver once (lazily) rather
		 * than reassigning it each time (which trips a maybe-uninitialized warning in TFLM's resolver
		 * move-assignment). */
		if (!resolver_ready_) {
			if (!BuildResolver(resolver_)) {
				return false;
			}
			resolver_ready_ = true;
		}

		/* Destroy any prior interpreter, then placement-new a fresh one over the same storage so an
		 * OTA model replace needs no dynamic allocation. interp_live_ tracks whether storage holds a
		 * constructed object (it does not the first time through). */
		if (interp_live_) {
			reinterpret_cast<tflite::MicroInterpreter *>(&interp_storage_)->~MicroInterpreter();
			interp_live_ = false;
		}
		interpreter_ = new (&interp_storage_)
		    tflite::MicroInterpreter(model, resolver_, arena_, arena_bytes_);
		interp_live_ = true;

		if (interpreter_->AllocateTensors() != kTfLiteOk) {
			interpreter_ = nullptr;
			return false;
		}
		present_ = true;
		return true;
	}

	/*
	 * Run the model over the conceptual input window WITHOUT materializing a float copy of it. `src`
	 * is the most-recent `src_len` int16 samples (interleaved [frame][channel], `channels` channels);
	 * they are conceptually right-aligned into a window of `win_len` elements with (win_len - src_len)
	 * leading ZEROS (front zero-pad), identical to what the old BuildImuWindow/BuildAudioWindow did.
	 *
	 * The normalization (per-channel mean over the FULL padded window, then divide by global max-abs
	 * of (value - mean) over the FULL padded window + 1e-6) and the int8 quantization are computed in
	 * three streaming passes reading from `src` directly and written straight into the input tensor.
	 * This reproduces the OLD math (BuildWindow front-zero-pad + Normalize + quantize) exactly.
	 * Returns a clf_result_t; UNKNOWN if not present or on any tensor mismatch.
	 */
	clf_result_t Infer(const int16_t *src, int src_len, int win_len, int channels)
	{
		clf_result_t out = { CLF_UNKNOWN, 0.0f };
		if (!present_ || interpreter_ == nullptr || win_len <= 0 || channels <= 0) {
			return out;
		}
		if (src_len < 0)        src_len = 0;
		if (src_len > win_len)  src_len = win_len;

		TfLiteTensor *in = interpreter_->input(0);
		if (in == nullptr || in->type != kTfLiteInt8) {
			return out;
		}
		const int in_count = static_cast<int>(in->bytes); /* int8 -> 1 byte/elem */
		if (in_count != win_len) {
			return out;   /* model shape doesn't match this stage's window , refuse rather than corrupt */
		}

		const int frames  = win_len / channels;
		const int pad_len  = win_len - src_len;  /* whole number of frames (multiple of channels) */

		/* PASS 1: per-channel mean over the FULL padded window. The (win_len - src_len) leading
		 * zero-pad samples contribute 0 to the sum but ARE counted in `frames`, matching the trainer's
		 * per-window norm over the zero-padded window. */
		float mean[IMU_AXES] = {0};   /* IMU_AXES (6) >= max channels used here */
		for (int i = 0; i < src_len; i++) {
			mean[i % channels] += static_cast<float>(src[i]);
		}
		for (int c = 0; c < channels; c++) {
			mean[c] /= static_cast<float>(frames);
		}

		/* PASS 2: global max-abs of (value - mean) over the FULL padded window. Zero-pad positions
		 * contribute |0 - mean[c]|. */
		float maxabs = 0.0f;
		if (pad_len > 0) {
			for (int c = 0; c < channels; c++) {
				const float a = std::fabs(mean[c]);
				if (a > maxabs) maxabs = a;
			}
		}
		for (int i = 0; i < src_len; i++) {
			const float a = std::fabs(static_cast<float>(src[i]) - mean[i % channels]);
			if (a > maxabs) maxabs = a;
		}
		const float inv = 1.0f / (maxabs + 1e-6f);

		/* PASS 3: quantize straight into the int8 tensor with its OWN scale/zero_point. */
		const float scale = in->params.scale;
		const int   zp    = in->params.zero_point;
		int8_t *q = in->data.int8;
		for (int i = 0; i < win_len; i++) {
			const int   c      = i % channels;
			const float sample = (i < pad_len) ? 0.0f : static_cast<float>(src[i - pad_len]);
			const float v      = (sample - mean[c]) * inv;
			int32_t qi = static_cast<int32_t>(std::lround(v / scale)) + zp;
			if (qi < -128) qi = -128;
			if (qi >  127) qi =  127;
			q[i] = static_cast<int8_t>(qi);
		}

		if (interpreter_->Invoke() != kTfLiteOk) {
			return out;
		}

		TfLiteTensor *o = interpreter_->output(0);
		if (o == nullptr || o->type != kTfLiteInt8) {
			return out;
		}
		const float oscale = o->params.scale;
		const int   ozp    = o->params.zero_point;
		const int   n      = static_cast<int>(o->bytes);

		int   best_idx = CLF_UNKNOWN;
		float best_val = -1.0f;
		for (int i = 0; i < n; i++) {
			const float prob = (static_cast<int>(o->data.int8[i]) - ozp) * oscale;
			if (prob > best_val) {
				best_val = prob;
				best_idx = i;
			}
		}
		out.cls = best_idx;
		out.confidence = best_val < 0.0f ? 0.0f : (best_val > 1.0f ? 1.0f : best_val);
		return out;
	}

private:
	uint8_t *arena_;
	size_t   arena_bytes_;
	bool     present_ = false;

	MeowOpResolver resolver_;
	bool           resolver_ready_ = false;
	tflite::MicroInterpreter *interpreter_ = nullptr;

	/* Raw, aligned storage so the interpreter can be placement-rebuilt on OTA model replace without
	 * heap. interp_live_ says whether it currently holds a constructed object. */
	alignas(tflite::MicroInterpreter) uint8_t interp_storage_[sizeof(tflite::MicroInterpreter)];
	bool interp_live_ = false;
};

/* The two stages. */
ModelSlot g_imu_slot(g_imu_arena, kImuArenaBytes);
ModelSlot g_audio_slot(g_audio_arena, kAudioArenaBytes);

} /* namespace */

/* ---- STRONG overrides of the weak cascade hooks (C linkage, exact signatures) ------------------ */

extern "C" bool clf_imu_model_present(void)
{
	return g_imu_slot.present();
}

extern "C" bool clf_audio_model_present(void)
{
	return g_audio_slot.present();
}

extern "C" clf_result_t imu_model_infer(const imu_features_t *feat)
{
	if (!g_imu_slot.present() || feat == nullptr || feat->samples == nullptr || feat->count == 0) {
		return (clf_result_t){ CLF_UNKNOWN, 0.0f };
	}
	/* Most-recent whole frames; the slot front-zero-pads to kImuWindow and quantizes from int16. */
	size_t avail = feat->count / kImuChannels;
	size_t take  = avail < (size_t)kImuFrames ? avail : (size_t)kImuFrames;
	const int16_t *src = feat->samples + (avail - take) * kImuChannels;
	return g_imu_slot.Infer(src, (int)(take * kImuChannels), kImuWindow, kImuChannels);
}

extern "C" clf_result_t audio_model_infer(const int16_t *pcm, size_t pcm_len)
{
	if (!g_audio_slot.present() || pcm == nullptr || pcm_len == 0) {
		return (clf_result_t){ CLF_UNKNOWN, 0.0f };
	}
	/* Most-recent samples; the slot front-zero-pads to kAudioWindow and quantizes from int16. */
	size_t take = pcm_len < (size_t)kAudioSamples ? pcm_len : (size_t)kAudioSamples;
	const int16_t *src = pcm + (pcm_len - take);
	return g_audio_slot.Infer(src, (int)take, kAudioWindow, kAudioChannels);
}

/* ---- Runtime model-load API (model_loader.h) --------------------------------------------------- */

extern "C" bool clf_set_imu_model(const uint8_t *buf, size_t len)
{
	return g_imu_slot.Load(buf, len);
}

extern "C" bool clf_set_audio_model(const uint8_t *buf, size_t len)
{
	return g_audio_slot.Load(buf, len);
}
