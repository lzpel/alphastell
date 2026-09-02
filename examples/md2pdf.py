#!/usr/bin/env python3
"""Markdown レポートを LaTeX 経由で PDF にする。

al_05〜09 が出す Markdown のサブセットだけを文字列操作で .tex に写し、tectonic でコンパイルする。
pandoc のような汎用変換ではなく、見出し・段落・強調・code・リンク・数式 ($ と $$)・画像・
パイプテーブル・リストだけを受け付ける。入力 .md が無ければ何もせず正常終了する
(makefile の al-% が全ターゲット共通で呼ぶため)。

	uv run examples/md2pdf.py out/al_05_blanket_3dplot.md
"""

import pathlib
import re
import subprocess
import sys

PREAMBLE = """\\documentclass{article}
\\usepackage[a4paper, margin=2cm]{geometry}
\\usepackage{xeCJK}
\\setCJKmainfont{Yu Gothic}
\\setmainfont{Yu Gothic}

\\usepackage{amsmath}
\\usepackage{graphicx}
\\usepackage{float}
\\usepackage[hidelinks]{hyperref}
\\setlength{\\parindent}{0pt}
\\setlength{\\parskip}{0.5em}
\\begin{document}
"""


def escape(text: str) -> str:
	"""テキスト部の LaTeX 特殊文字を無害化する (数式と code は通さないこと)。"""
	for char, replacement in (("%", "\\%"), ("&", "\\&"), ("#", "\\#"), ("_", "\\_"), ("~", "\\textasciitilde{}"), ("^", "\\textasciicircum{}")):
		text = text.replace(char, replacement)
	return text


def inline(text: str) -> str:
	"""段落内のインライン要素を変換する。数式 $...$ は素通し、それ以外はエスケープする。"""
	pattern = re.compile(r"(\$[^$]+\$)|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*")
	pieces = []
	position = 0
	for match in pattern.finditer(text):
		pieces.append(escape(text[position : match.start()]))
		math, code, link_text, link_url, bold = match.groups()
		if math is not None:
			pieces.append(math)
		elif code is not None:
			pieces.append("\\texttt{" + escape(code) + "}")
		elif link_text is not None:
			pieces.append("\\href{" + link_url + "}{" + escape(link_text) + "}")
		else:
			pieces.append("\\textbf{" + escape(bold) + "}")
		position = match.end()
	pieces.append(escape(text[position:]))
	return "".join(pieces)


def table(rows: list[str]) -> str:
	"""パイプテーブルを tabular にする。2 行目の :--/:-:/--: が列の寄せを決める。"""
	cells = [[cell.strip() for cell in row.strip().strip("|").split("|")] for row in rows]
	spec = "".join("c" if cell.startswith(":") and cell.endswith(":") else "r" if cell.endswith(":") else "l" for cell in cells[1])
	body = [" & ".join(inline(cell) for cell in row) + " \\\\" for row in [cells[0]] + cells[2:]]
	return "\\begin{center}\\begin{tabular}{" + spec + "}\n\\hline\n" + body[0] + "\n\\hline\n" + "\n".join(body[1:]) + "\n\\hline\n\\end{tabular}\\end{center}"


def convert(markdown: str) -> str:
	"""Markdown 本文を LaTeX 本文にする行単位の状態機械。"""
	lines = markdown.splitlines()
	output = []
	index = 0
	while index < len(lines):
		line = lines[index]
		if line.strip() == "$$":  # ブロック数式。閉じ $$ まで素通し
			block = []
			index += 1
			while lines[index].strip() != "$$":
				block.append(lines[index])
				index += 1
			output.append("\\[\n" + "\n".join(block) + "\n\\]")
		elif heading := re.match(r"(#{1,3}) +(.*)", line):
			command = {1: "section", 2: "subsection", 3: "subsubsection"}[len(heading.group(1))]
			output.append(f"\\{command}*{{{inline(heading.group(2))}}}")
		elif image := re.match(r"!\[(.*)\]\((\S+)\)\s*$", line):
			caption = f"\\caption{{{inline(image.group(1))}}}\n" if image.group(1) else ""
			output.append("\\begin{figure}[H]\\centering\n\\includegraphics[width=0.85\\linewidth]{" + image.group(2) + "}\n" + caption + "\\end{figure}")
		elif line.lstrip().startswith("|"):
			rows = []
			while index < len(lines) and lines[index].lstrip().startswith("|"):
				rows.append(lines[index])
				index += 1
			output.append(table(rows))
			continue
		elif re.match(r"- ", line) or re.match(r"\d+\. ", line):
			environment = "itemize" if line.startswith("- ") else "enumerate"
			items = []
			while index < len(lines) and (item := re.match(r"(?:- |\d+\. )(.*)", lines[index])):
				items.append("\\item " + inline(item.group(1)))
				index += 1
			# 箇条書きの継続行 (インデントされた行) は直前の item に連結する
			output.append(f"\\begin{{{environment}}}\n" + "\n".join(items) + f"\n\\end{{{environment}}}")
			continue
		else:
			output.append(inline(line))
		index += 1
	return "\n".join(output)


def main(markdown: pathlib.Path) -> None:
	if not markdown.exists():
		print(f"{markdown}: not found, nothing to convert")
		return
	tex = markdown.with_suffix(".tex")
	tex.write_text(PREAMBLE + convert(markdown.read_text(encoding="utf-8")) + "\n\\end{document}\n", encoding="utf-8")
	# 相対パスの画像参照を解決するため、md のあるディレクトリで tectonic を走らせる
	subprocess.run(["tectonic", tex.name], cwd=markdown.parent, check=True)
	pdf = markdown.with_suffix(".pdf")
	print(f"{pdf}: {pdf.stat().st_size} bytes")


if __name__ == "__main__":
	main(pathlib.Path(sys.argv[1]))
