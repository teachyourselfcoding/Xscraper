1.	Make sure you have:
	•	pandoc installed: brew install pandoc (macOS)
	•	wkhtmltopdf or weasyprint (for better image support)

2. Run:
   - pandoc your_file.md -o output.pdf

3. To include images and control layout, try: 
   - pandoc your_file.md -o output.pdf --pdf-engine=wkhtmltopdf
   - 
4. To scrape a particular date
   - SCRAPE_DATE=2025-06-25 python scraper.py
