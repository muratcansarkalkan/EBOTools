"""Standalone NBA Live FSH Tool.

Runs outside Blender using the same fsh_archive.py / synthetic_fsh.py core used
by the Blender add-on. No GX/Gimex or third-party Python packages are required.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import traceback

try:
    from . import fsh_archive, synthetic_fsh
except ImportError:
    import fsh_archive
    import synthetic_fsh


APP_TITLE = "NBA Live FSH Tool"
SUPPORTED_IMAGE_SUFFIXES = {".png"}


def png_map(folder: str | Path) -> dict[str, Path]:
    root = Path(folder).resolve()
    if not root.is_dir():
        raise ValueError(f"Image folder does not exist: {root}")
    textures: dict[str, Path] = {}
    for path in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            continue
        name = path.stem
        try:
            name = synthetic_fsh._validate_asset_name(name)
        except synthetic_fsh.SyntheticFshError as exc:
            raise ValueError(f"{path.name}: {exc}") from exc
        if name in textures:
            raise ValueError(f"Duplicate TextureName {name!r} in {root}.")
        textures[name] = path
    if not textures:
        raise ValueError(f"No PNG textures found in {root}.")
    return textures


def extract_many(paths: list[str | Path], output_root: str | Path) -> list[Path]:
    out = Path(output_root).resolve()
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for raw in paths:
        archive = fsh_archive.read_fsh(raw)
        results.append(fsh_archive.extract_archive(archive, out))
    return results


def rebuild_many(
    paths: list[str | Path],
    texture_root: str | Path,
    output_root: str | Path,
) -> list[Path]:
    textures = Path(texture_root).resolve()
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for raw in paths:
        archive = fsh_archive.read_fsh(raw)
        folder = textures / archive.path.stem
        if not folder.is_dir() and len(paths) == 1:
            # Convenience: a directly selected extracted folder is valid for one archive.
            folder = textures
        results.append(fsh_archive.repack_archive(archive, folder, output))
    return results


def _creation_folders(input_root: str | Path) -> list[Path]:
    root = Path(input_root).resolve()
    if not root.is_dir():
        raise ValueError(f"Input folder does not exist: {root}")
    folders: list[Path] = []
    if any(p.is_file() and p.suffix.lower() == ".png" for p in root.iterdir()):
        folders.append(root)
    folders.extend(
        p for p in sorted(root.iterdir(), key=lambda p: p.name.lower())
        if p.is_dir() and any(c.is_file() and c.suffix.lower() == ".png" for c in p.iterdir())
    )
    if not folders:
        raise ValueError(
            f"No PNG files were found in {root} or its immediate subfolders."
        )
    return folders


def create_many(input_root: str | Path, output_root: str | Path) -> list[Path]:
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for folder in _creation_folders(input_root):
        textures = png_map(folder)
        target = output / f"{folder.name}.fsh"
        result = synthetic_fsh.create_native_fsh(textures, target)
        results.append(Path(result["path"]))
    return results


def _cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Native NBA Live ShpF FSH utility")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("extract", help="Extract one or more FSH archives to PNG folders")
    p.add_argument("files", nargs="+", help="FSH files")
    p.add_argument("-o", "--output", required=True, help="Output root")

    p = sub.add_parser("rebuild", help="Rebuild one or more FSH archives from extracted PNG folders")
    p.add_argument("files", nargs="+", help="Original FSH files")
    p.add_argument("-t", "--textures", required=True, help="Texture root")
    p.add_argument("-o", "--output", required=True, help="Output root")

    p = sub.add_parser("create", help="Create one or many FSH files from PNG folders")
    p.add_argument("input", help="PNG folder or parent folder containing PNG subfolders")
    p.add_argument("-o", "--output", required=True, help="Output root")
    return parser


def run_cli(argv: list[str]) -> int:
    parser = _cli()
    args = parser.parse_args(argv)
    try:
        if args.command == "extract":
            results = extract_many(args.files, args.output)
        elif args.command == "rebuild":
            results = rebuild_many(args.files, args.textures, args.output)
        elif args.command == "create":
            results = create_many(args.input, args.output)
        else:
            parser.print_help()
            return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    for path in results:
        print(path)
    return 0


def run_gui() -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception as exc:
        print(f"Tkinter is unavailable: {exc}", file=sys.stderr)
        return 1

    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("790x610")
    root.minsize(700, 520)

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=10, pady=10)

    status_var = tk.StringVar(value="Ready. Native FSH; GX/Gimex is not required.")

    def set_status(text: str):
        status_var.set(text)
        root.update_idletasks()

    def show_error(exc: Exception):
        set_status(f"Error: {exc}")
        messagebox.showerror(APP_TITLE, str(exc), parent=root)

    # Extract ---------------------------------------------------------------
    extract_tab = ttk.Frame(notebook, padding=12)
    notebook.add(extract_tab, text="Extract FSH")
    extract_files: list[str] = []
    extract_files_var = tk.StringVar(value="No FSH files selected")
    extract_out_var = tk.StringVar()

    def choose_extract_files():
        nonlocal extract_files
        values = filedialog.askopenfilenames(
            parent=root,
            title="Select FSH archives",
            filetypes=[("NBA Live FSH", "*.fsh"), ("All files", "*.*")],
        )
        if values:
            extract_files = list(values)
            extract_files_var.set(f"{len(extract_files)} FSH file(s) selected")

    def choose_extract_out():
        value = filedialog.askdirectory(parent=root, title="Choose extraction output folder")
        if value:
            extract_out_var.set(value)

    def do_extract():
        try:
            if not extract_files:
                raise ValueError("Select at least one FSH file.")
            if not extract_out_var.get():
                raise ValueError("Choose an output folder.")
            set_status(f"Extracting {len(extract_files)} archive(s)...")
            results = extract_many(extract_files, extract_out_var.get())
            set_status(f"Extracted {len(results)} archive(s).")
            messagebox.showinfo(
                APP_TITLE,
                f"Extracted {len(results)} archive(s) successfully.",
                parent=root,
            )
        except Exception as exc:
            show_error(exc)

    ttk.Label(extract_tab, text="Batch extract FSH archives to editable PNG folders.").pack(anchor="w", pady=(0, 12))
    ttk.Button(extract_tab, text="Select FSH Files...", command=choose_extract_files).pack(anchor="w")
    ttk.Label(extract_tab, textvariable=extract_files_var).pack(anchor="w", pady=(4, 12))
    ttk.Button(extract_tab, text="Output Folder...", command=choose_extract_out).pack(anchor="w")
    ttk.Entry(extract_tab, textvariable=extract_out_var).pack(fill="x", pady=(4, 16))
    ttk.Button(extract_tab, text="Extract", command=do_extract).pack(anchor="w")

    # Rebuild ---------------------------------------------------------------
    rebuild_tab = ttk.Frame(notebook, padding=12)
    notebook.add(rebuild_tab, text="Rebuild FSH")
    rebuild_files: list[str] = []
    rebuild_files_var = tk.StringVar(value="No original FSH files selected")
    rebuild_tex_var = tk.StringVar()
    rebuild_out_var = tk.StringVar()

    def choose_rebuild_files():
        nonlocal rebuild_files
        values = filedialog.askopenfilenames(
            parent=root,
            title="Select original FSH archives",
            filetypes=[("NBA Live FSH", "*.fsh"), ("All files", "*.*")],
        )
        if values:
            rebuild_files = list(values)
            rebuild_files_var.set(f"{len(rebuild_files)} original FSH file(s) selected")

    def choose_rebuild_tex():
        value = filedialog.askdirectory(parent=root, title="Choose extracted texture root")
        if value:
            rebuild_tex_var.set(value)

    def choose_rebuild_out():
        value = filedialog.askdirectory(parent=root, title="Choose rebuilt FSH output folder")
        if value:
            rebuild_out_var.set(value)

    def do_rebuild():
        try:
            if not rebuild_files:
                raise ValueError("Select at least one original FSH file.")
            if not rebuild_tex_var.get():
                raise ValueError("Choose the extracted texture root.")
            if not rebuild_out_var.get():
                raise ValueError("Choose an output folder.")
            set_status(f"Rebuilding {len(rebuild_files)} archive(s)...")
            results = rebuild_many(rebuild_files, rebuild_tex_var.get(), rebuild_out_var.get())
            set_status(f"Rebuilt {len(results)} archive(s).")
            messagebox.showinfo(
                APP_TITLE,
                f"Rebuilt {len(results)} archive(s) successfully.",
                parent=root,
            )
        except Exception as exc:
            show_error(exc)

    ttk.Label(
        rebuild_tab,
        text="Rebuild from folders created by Extract FSH. The original archive preserves its layout/order.",
        wraplength=720,
    ).pack(anchor="w", pady=(0, 12))
    ttk.Button(rebuild_tab, text="Select Original FSH Files...", command=choose_rebuild_files).pack(anchor="w")
    ttk.Label(rebuild_tab, textvariable=rebuild_files_var).pack(anchor="w", pady=(4, 12))
    ttk.Button(rebuild_tab, text="Extracted Texture Root...", command=choose_rebuild_tex).pack(anchor="w")
    ttk.Entry(rebuild_tab, textvariable=rebuild_tex_var).pack(fill="x", pady=(4, 12))
    ttk.Button(rebuild_tab, text="Output Folder...", command=choose_rebuild_out).pack(anchor="w")
    ttk.Entry(rebuild_tab, textvariable=rebuild_out_var).pack(fill="x", pady=(4, 16))
    ttk.Button(rebuild_tab, text="Rebuild", command=do_rebuild).pack(anchor="w")

    # Create ----------------------------------------------------------------
    create_tab = ttk.Frame(notebook, padding=12)
    notebook.add(create_tab, text="Create FSH")
    create_in_var = tk.StringVar()
    create_out_var = tk.StringVar()

    def choose_create_in():
        value = filedialog.askdirectory(parent=root, title="Choose PNG folder or parent folder")
        if value:
            create_in_var.set(value)

    def choose_create_out():
        value = filedialog.askdirectory(parent=root, title="Choose FSH output folder")
        if value:
            create_out_var.set(value)

    def do_create():
        try:
            if not create_in_var.get():
                raise ValueError("Choose a PNG input folder.")
            if not create_out_var.get():
                raise ValueError("Choose an output folder.")
            set_status("Creating FSH archive(s)...")
            results = create_many(create_in_var.get(), create_out_var.get())
            set_status(f"Created {len(results)} FSH archive(s).")
            messagebox.showinfo(
                APP_TITLE,
                f"Created {len(results)} FSH archive(s) successfully.",
                parent=root,
            )
        except Exception as exc:
            show_error(exc)

    ttk.Label(
        create_tab,
        text=(
            "PNG filename becomes TextureName. If the selected folder contains PNGs, it creates one FSH named "
            "after that folder. Immediate subfolders containing PNGs are also exported, allowing many FSH files "
            "in one operation. RGB images become DXT1; images with alpha become DXT5."
        ),
        wraplength=720,
        justify="left",
    ).pack(anchor="w", pady=(0, 12))
    ttk.Button(create_tab, text="PNG Folder / Parent Folder...", command=choose_create_in).pack(anchor="w")
    ttk.Entry(create_tab, textvariable=create_in_var).pack(fill="x", pady=(4, 12))
    ttk.Button(create_tab, text="Output Folder...", command=choose_create_out).pack(anchor="w")
    ttk.Entry(create_tab, textvariable=create_out_var).pack(fill="x", pady=(4, 16))
    ttk.Button(create_tab, text="Create FSH File(s)", command=do_create).pack(anchor="w")

    footer = ttk.Frame(root, padding=(10, 0, 10, 10))
    footer.pack(fill="x")
    ttk.Separator(footer).pack(fill="x", pady=(0, 7))
    ttk.Label(footer, textvariable=status_var).pack(anchor="w")

    root.mainloop()
    return 0


def main() -> int:
    if len(sys.argv) > 1:
        return run_cli(sys.argv[1:])
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
