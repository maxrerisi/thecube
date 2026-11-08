"""Render pixel-devil candidates to one comparison PNG (stdlib SVG -> magick)."""
import subprocess, sys, pathlib
PAL = {"O":"#0a1a3b","B":"#1f5fbf","L":"#5c8fe0","D":"#163f86","H":"#f2f2f2","h":"#c9ccd6",
       "W":"#ffffff","K":"#0d0d14","P":"#ff8fa3","M":"#3a0a1a","T":"#ffffff","S":"#8fd4ff",
       "R":"#e8344e","F":"#c9a227","f":"#8a6d10"}
D = {}
D["current"] = [
".H..........H.",".HH........HH.","..HOOOOOOOOH..","..OBBBBBBBBO..",".OBLBBBBBBBBO.",
".OBWWBBBBWWBO.",".OBWKBBBBWKBO.",".OBBBBBBBBBBO.",".OPBBBBBBBBPO.",".OBBBMMMMBBBO.",
"..OBBBBBBBBO..","...OOOOOOOO...","...OO....OO..."]
# A: big head, curved horns, brows, fanged grin
D["A_grin"] = [
"..O..........O..",
".OHO........OHO.",
".OHHO......OHhO.",
"..OHhOOOOOOhHO..",
"..OOBBBBBBBBOO..",
".OBLLBBBBBBBBBO.",
".OBLBBBBBBBBBBO.",
".OBKKKBBBBKKKBO.",
".OBBWWBBBBWWBBO.",
".OBBWKBBBBKWBBO.",
".OPPBBBBBBBBPPO.",
".OBBMMMMMMMMBBO.",
".OBBMTMMMMTMBBO.",
"..OBBMMMMMMBBO..",
"..ODBBBBBBBBDO..",
"...OODDDDDDOO...",
".....OOOOOO.....",
]
# B: chibi full body with tail + tiny fork
D_old = [
"..O........O......",
".OHO......OHO.....",
".OHhOOOOOOhHO.....",
"..OBBBBBBBBO......",
".OBLLBBBBBBBO.....",
".OBLWWBBBWWBO..F.F",
".OBBWKBBBKWBO..FFF",
".OPBBBBBBBBPO...f.",
".OBBBMMMMBBBO...f.",
"..OBBBTTBBBO....f.",
"...OOOOOOOO.....f.",
"..OBOBBBBOBO...Of.",
"..OBOBLBBOBOO.OOf.",
"...OOBBBBOO.OOR.f.",
"....OBBBBO.......",
"....OBOOBO........",
"....OO..OO........",
]
# C: round blob, big sparkly eyes, small horns, smile (tamagotchi)
D["C_blob"] = [
"....O......O....",
"...OHO....OHO...",
"...OHOOOOOOHO...",
"..OOBBBBBBBBOO..",
".OBLLBBBBBBBBBO.",
".OBLBBBBBBBBBBO.",
"OBBWWWBBBBWWWBBO",
"OBBWKKBBBBWKKBBO",
"OBBWKKBBBBWKKBBO",
"OBPPBBBBBBBBPPBO",
"OBBBBBMBBMBBBBBO",
"OBBBBBBMMBBBBBBO",
".OBBBBBBBBBBBBO.",
".ODBBBBBBBBBBDO.",
"..ODDDDDDDDDDO..",
"...OOOOOOOOOO...",
]
D["B2_fork"] = [
"..O........O....",
".OHO......OHO...",
".OHhOOOOOOhHOF.F",
"..OBBBBBBBBO.FFF",
".OBLLBBBBBBBO.f.",
".OBLWWBBBWWBO.f.",
".OBBWKBBBKWBO.f.",
".OPBBBBBBBBPO.f.",
".OBBBMMMMBBBO.f.",
"..OBBBTTBBBO..f.",
"...OOOOOOOO...f.",
"..OBBBBBBBBOOOf.",
".OBOBLBBBBOBBBf.",
".OBOBBBBBBOOOOf.",
"..OOBBBBBBO...f.",
"...OBBBBBBO...f.",
"...OBBOOBBO.....",
"...OOO..OOO.....",
]
def svg(name, rows, cell, x0, y0):
    out = []
    for y, r in enumerate(rows):
        for x, ch in enumerate(r):
            if ch in PAL:
                out.append(f'<rect x="{x0+x*cell}" y="{y0+y*cell}" width="{cell}" height="{cell}" fill="{PAL[ch]}"/>')
    return "".join(out)
cell, pad, W = 14, 40, 0
items = list(D.items())
for n, r in items:
    print(n, {len(x) for x in r}, len(r))
col = 18*cell + pad
W = col*len(items) + pad; H = 18*cell + 2*pad + 30
body = "".join(svg(n, r, cell, pad + i*col, pad) + f'<text x="{pad+i*col}" y="{H-14}" font-family="Helvetica" font-size="22" fill="#333">{n}</text>' for i,(n,r) in enumerate(items))
p = pathlib.Path(sys.argv[1])
p.with_suffix(".svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"><rect width="100%" height="100%" fill="#f4f1ea"/>{body}</svg>')
subprocess.run(["magick", str(p.with_suffix(".svg")), str(p)], check=True)
