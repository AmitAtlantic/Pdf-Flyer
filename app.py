from flask import Flask, request, render_template, send_file, jsonify
from flask_cors import CORS
import pdfkit
import io
import os
import html

app = Flask(__name__)

# Allow CORS for local testing or specify your domain in production
CORS(app, resources={r"/generate-pdf": {"origins": "*"}})

# Path to wkhtmltopdf
WKHTMLTOPDF_PATH = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
if not os.path.exists(WKHTMLTOPDF_PATH):
    raise FileNotFoundError(f"wkhtmltopdf not found at {WKHTMLTOPDF_PATH}")

config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)

@app.route('/generate-pdf', methods=['POST', 'OPTIONS'])
def generate_pdf():
    # Respond to preflight request
    if request.method == 'OPTIONS':
        return '', 204

    try:
        data = request.get_json()
        print(data)
        if not data:
            return jsonify({"error": "No JSON data received"}), 400

        TOC_CHAR_LIMIT = 1445
        # Process Table of Contents
        toc_raw = html.unescape(data.get('toc', ''))
        toc = toc_raw[:TOC_CHAR_LIMIT]
        if len(toc_raw) > TOC_CHAR_LIMIT:
            toc += "\n[... check website to see more]"

        # Set character limit
        CHAR_LIMIT = 1300  # Adjust as needed
        # Process About the Book
        book_desc_raw = html.unescape(data.get('book_desc', ''))
        book_desc = book_desc_raw[:CHAR_LIMIT]
        if len(book_desc_raw) > CHAR_LIMIT:
            book_desc += "\n[... check website to see more]"

            
        # Process About the Book
        book_desc_raw = html.unescape(data.get('book_desc', ''))
        book_desc = book_desc_raw[:CHAR_LIMIT]
        if len(book_desc_raw) > CHAR_LIMIT:
            book_desc += "\n[... check website to see more]"

        # Process About the Author
        about_author_raw = html.unescape(data.get('about_author', ''))
        about_author = about_author_raw[:CHAR_LIMIT]
        if len(about_author_raw) > CHAR_LIMIT:
            about_author += "\n[... check website to see more]"

        # Render HTML with template
        rendered_html = render_template(
            'flyer_template.html',
            product_title=data.get('product_title'),
            product_image=data.get('product_image'),
            product_category=data.get('product_category'),
            publisher_imprint=data.get('publisher'),
            edition=data.get('edition'),
            volume=data.get('volume'),
            publishing_date=data.get('publishing_date'),
            pages=data.get('pages'),
            isbn=data.get('isbn'),
            author=data.get('author'),
            variants=data.get('variants'),
            price=data.get('price'),
            book_desc=book_desc,
            about_author=about_author,
            toc=toc
        )

        # PDF generation options
        options = {
            'page-size': 'A4',
            'encoding': 'UTF-8',
            'margin-top': '0',
            'margin-right': '0',
            'margin-bottom': '0',
            'margin-left': '0',
            'zoom': '1',
        }

        # Create PDF
        pdf = pdfkit.from_string(rendered_html, False, configuration=config, options=options)

        return send_file(
            io.BytesIO(pdf),
            download_name=f"{data.get('product_title', 'flyer')}_flyer.pdf",
            mimetype='application/pdf'
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
