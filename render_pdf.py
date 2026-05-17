import sys
from weasyprint import HTML
HTML(filename=sys.argv[1]).write_pdf(sys.argv[2])
print(f"PDF written: {sys.argv[2]}")
