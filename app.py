from flask import Flask, request, render_template, send_file, jsonify
from flask_cors import CORS
import pdfkit
import io
import os
import html
from bs4 import BeautifulSoup

app = Flask(__name__)
CORS(app, resources={r"/generate-pdf": {"origins": "*"}})

WKHTMLTOPDF_PATH = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
if not os.path.exists(WKHTMLTOPDF_PATH):
    raise FileNotFoundError(f"wkhtmltopdf not found at {WKHTMLTOPDF_PATH}")

config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)

# Helper function to truncate HTML while preserving tag structure
def truncate_html_preserving_tags(html_content, char_limit):
    soup = BeautifulSoup(html_content, 'html.parser')
    total_chars = 0

    def truncate_node(node):
        nonlocal total_chars
        if node.name is None:  # NavigableString
            if total_chars >= char_limit:
                node.extract()
                return
            text_len = len(node)
            if total_chars + text_len > char_limit:
                node.replace_with(node[:char_limit - total_chars])
                total_chars = char_limit
            else:
                total_chars += text_len
        else:
            for child in list(node.contents):
                if total_chars >= char_limit:
                    child.extract()
                else:
                    truncate_node(child)

    truncate_node(soup)

    if total_chars >= char_limit:
        note = soup.new_tag("p")
        note.string = "[... check website to see more]"
        soup.append(note)

    return str(soup)

@app.route('/generate-pdf', methods=['POST', 'OPTIONS'])
def generate_pdf():
    if request.method == 'OPTIONS':
        return '', 204

    try:
        data = request.get_json()
        print(data)
        if not data:
            return jsonify({"error": "No JSON data received"}), 400

        # Character limits
        TOC_CHAR_LIMIT = 900
        CHAR_LIMIT = 1200

        # Process Table of Contents (HTML safe)
        toc_raw = html.unescape(data.get('toc', ''))
        toc = truncate_html_preserving_tags(toc_raw, TOC_CHAR_LIMIT)

        # Process About the Book (HTML safe)
        book_desc = html.unescape(data.get('book_desc', ''))
        # book_desc = truncate_html_preserving_tags(book_desc_raw, CHAR_LIMIT)

        # Process About the Author (HTML safe)
        about_author = html.unescape(data.get('about_author', ''))
        # about_author = truncate_html_preserving_tags(about_author_raw, CHAR_LIMIT)

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
