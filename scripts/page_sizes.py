"""Add artifact byte counts at the bottom of every published HTML page."""
from pathlib import Path
import re

root = Path(__file__).resolve().parent.parent / 'site'
pattern = re.compile(r'<!-- page-sizes -->.*?<!-- /page-sizes -->', re.S)
pages = {p: pattern.sub('', p.read_text()) for p in root.rglob('*.html')}
files = [p for p in root.rglob('*') if p.is_file()]
other_bytes = sum(p.stat().st_size for p in files if p not in pages)
sizes = {p: len(content.encode()) for p, content in pages.items()}

for _ in range(12):
    total = other_bytes + sum(sizes.values())
    rendered = {}
    for path, original in pages.items():
        footer = ('<!-- page-sizes --><footer aria-label="配信容量" style="padding:1rem;font-size:.8rem;overflow-wrap:anywhere">'
                  f'このHTML {sizes[path]:,} bytes · サイト全体 {total:,} bytes（TTL・JSONを含む非圧縮サイズ）'
                  '</footer><!-- /page-sizes -->')
        end = '</body>' if '</body>' in original else '</html>'
        rendered[path] = original.replace(end, footer + end, 1) if end in original else original + footer
    updated = {p: len(content.encode()) for p, content in rendered.items()}
    if updated == sizes:
        for path, content in rendered.items():
            path.write_text(content)
        break
    sizes = updated
else:
    raise RuntimeError('artifact size did not stabilize')
print(f'Published artifact: {total} bytes, {len(pages)} pages')
