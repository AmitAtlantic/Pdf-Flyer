from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import io

app = Flask(__name__)
CORS(app)  # Enable CORS for cross-origin requests

@app.route('/generate-pdf', methods=['POST'])
def generate_pdf():
    try:
        # Get JSON data from AJAX request
        data = request.json
        print(data)
        if not data:
            return jsonify({"error": "No data provided"}), 400

        # Extract data fields
        title = data.get('title', 'Default Title')
        content = data.get('content', 'No content provided')

        # Create a PDF in memory
        pdf_buffer = io.BytesIO()
        pdf = canvas.Canvas(pdf_buffer, pagesize=letter)
        pdf.setTitle(title)

        # Add design and content to the PDF
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(100, 750, title)

        pdf.setFont("Helvetica", 12)
        pdf.drawString(100, 730, content)

        # Add a simple line for design
        pdf.line(50, 720, 550, 720)

        pdf.save()
        pdf_buffer.seek(0)

        # Send the PDF as a response
        return send_file(pdf_buffer, as_attachment=True, download_name="output.pdf", mimetype='application/pdf')

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)