# Meowtion technical documentation (LaTeX)

The complete technical reference for Meowtion, built with XeLaTeX + Biber. No Perl or
`latexmk` is required; the build passes are run by a small PowerShell script.

A prebuilt copy is committed as [`meowtion-technical.pdf`](meowtion-technical.pdf) so you can
read it without a LaTeX toolchain. Every full build refreshes it automatically, so the committed
PDF always matches the sources, just rebuild and commit.

## Build

From this folder (`docs/technical/`):

```powershell
.\build.ps1            # full build: xelatex, biber, xelatex, xelatex  ->  build/main.pdf
.\build.ps1 -Quick     # single pass (fast, skips the bibliography)
.\build.ps1 -Clean     # delete the build/ folder
.\build.ps1 -View      # build, then open the PDF
.\build.ps1 -Clean -Full -View   # clean rebuild and open
```

Everything LaTeX generates goes in `build/` (git-ignored). The finished PDF is
`build/main.pdf`.

### VS Code buttons

With the repository open in VS Code, the **Tasks** extension (`actboy168.tasks`, recommended
in `.vscode/extensions.json`) shows these as status-bar buttons:

- **LaTeX: Build doc** — full build
- **LaTeX: Quick build** — single pass
- **LaTeX: Clean** — remove `build/`
- **LaTeX: View PDF** — build and open

They are also available via the command palette (`Tasks: Run Task`).

## Layout

```
docs/technical/
├── main.tex              master file: \input order of all sections
├── build.ps1            XeLaTeX + Biber build (no Perl/latexmk)
├── references.bib       bibliography
├── README.md            this file
├── preamble/
│   ├── packages.tex     package imports
│   ├── style.tex        brand colours, headings, headers/footers, code listings
│   └── metadata.tex     title, author, version macros
├── frontmatter/
│   └── titlepage.tex    branded cover page (transparent logo.png + typeset wordmark)
└── sections/
    ├── 01-introduction.tex
    ├── 02-system-overview.tex
    ├── 03-hardware.tex
    ├── 04-firmware-collar.tex
    ├── 05-firmware-station.tex
    ├── 06-on-device-ai.tex
    ├── 07-training-pipeline.tex
    ├── 08-cloud-backend.tex
    ├── 09-dashboard.tex
    ├── 10-protocols.tex
    ├── 11-security-privacy.tex
    └── 12-future-work.tex
```

Sections are numbered so the file order matches the document order. To add a section, drop a
new `sections/NN-name.tex` and add one `\input{sections/NN-name}` line to `main.tex`.

## Conventions

- One file per section, kept self-contained, with a `\label{sec:...}` at the top so other
  sections can `\cref{}` it.
- Figures resolve by filename via `\graphicspath` (this folder, `docs/`, and the
  `hardware/images/...` trees), so `\includegraphics{exploded.png}` just works.
- Code goes in `lstlisting` with the shared `mw` style; no external highlighter needed.
