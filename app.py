from flask import Flask, request, render_template, send_file, jsonify
from flask_cors import CORS
import pdfkit
import io
import os
import html

app = Flask(__name__)

# 👇 Replace with your actual domain (or use '*' temporarily to test)
CORS(app, resources={r"/generate-pdf": {"origins": "*"}})

# Path to wkhtmltopdf
WKHTMLTOPDF_PATH = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
if not os.path.exists(WKHTMLTOPDF_PATH):
    raise FileNotFoundError(f"wkhtmltopdf not found at {WKHTMLTOPDF_PATH}")

config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)

@app.route('/generate-pdf', methods=['POST', 'OPTIONS'])
def generate_pdf():
    # 👇 Respond to the preflight OPTIONS request
    if request.method == 'OPTIONS':
        return '', 204

    try:
        data = request.get_json()
        print(data)
        if not data:
            return jsonify({"error": "No JSON data received"}), 400

        rendered_html = render_template(
            'flyer_template.html',
            product_title=data.get('product_title'),
            product_image=data.get('product_image'),
            product_category=data.get('product_category'),
            imprint=data.get('imprint'),
            publishing_date=data.get('publishing_date'),
            pages=data.get('pages'),
            isbn=data.get('isbn'),
            author=data.get('author'),
            variants=data.get('variants'),
            price=data.get('price'),
            book_desc=html.unescape(data.get('book_desc', '')),
            about_author=html.unescape(data.get('about_author','')),
            toc=html.unescape(data.get('toc','')),
        )

        options = {
            'page-size': 'A4',
            'encoding': 'UTF-8',
            'margin-top': '0',
            'margin-right': '0',
            'margin-bottom': '0',
            'margin-left': '0',
            'zoom': '1',  # You can adjust this down to fit large content
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
