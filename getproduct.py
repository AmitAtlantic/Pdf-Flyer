from flask import Flask, request, render_template, send_file, jsonify
from flask_cors import CORS
import pdfkit
import io
import os
from bs4 import BeautifulSoup
import requests
from datetime import datetime

app = Flask(__name__)
CORS(app, resources={r"/getproduct": {"origins": "*"}})

# PDF Tool Config
WKHTMLTOPDF_PATH = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
if not os.path.exists(WKHTMLTOPDF_PATH):
    raise FileNotFoundError(f"wkhtmltopdf not found at {WKHTMLTOPDF_PATH}")
config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)

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
        note.string = "[... visit our website to learn more]"
        soup.append(note)

    return str(soup)

# Shopify API Config
SHOPIFY_DOMAIN = "wcenvi-rh.myshopify.com"
SHOPIFY_ACCESS_TOKEN = "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"
def safe_get(dictionary, keys, default=''):
    """Safely get nested dictionary keys"""
    if not isinstance(keys, list):
        keys = [keys]
    try:
        for key in keys:
            dictionary = dictionary.get(key)
            if dictionary is None:
                return default
        return dictionary
    except (AttributeError, TypeError):
        return default
 
def fetch_products_by_skus(skus):

    if not skus or not isinstance(skus, str):
        return None, ["Invalid SKUs input. It must be a non-empty string."]
    
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    try:
        query = """
        query GetProductsBySkus($query: String!) {
          productVariants(first: 25, query: $query) {
            edges {
              node {
                sku
                title
                price
                product {
                  title
                  productType
                  featuredImage {
                    url
                  }
                  variants(first: 10) {
                    edges {
                      node {
                        sku
                        title
                        price
                        metafield(namespace: "custom", key: "edition") {
                          value
                        }
                      }
                    }
                  }
                  metafields(first: 100) {
                    edges {
                      node {
                        namespace
                        key
                        value
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """
        variables = {
            "query": skus
        }
        response = requests.post(
            f"https://{SHOPIFY_DOMAIN}/admin/api/2025-04/graphql.json",
            json={'query': query, 'variables': variables},
            headers=headers
        )
        response.raise_for_status()

        data = response.json()

        if safe_get(data, 'errors'):
            errors = [err.get('message', 'Unknown GraphQL error') for err in safe_get(data, 'errors', [])]
            return None, errors

        edges = safe_get(data, ['data', 'productVariants', 'edges'], [])
        if not edges:
            return None, ["No products found for the given SKUs."]

        products_by_sku = {}
        errors = []

        for edge in edges:
            try:
                node = safe_get(edge, 'node', {})
                sku = safe_get(node, 'sku')
                if not sku:
                    continue

                product = safe_get(node, 'product', {})

                # Process metafields
                metafield_edges = safe_get(product, ['metafields', 'edges'], [])
                metafields = {}
                for mf in metafield_edges:
                    mf_node = safe_get(mf, 'node', {})
                    namespace = safe_get(mf_node, 'namespace')
                    key = safe_get(mf_node, 'key')
                    value = safe_get(mf_node, 'value')
                    if namespace and key and value is not None:
                        metafields[f"{namespace}_{key}"] = value

                # Get edition from variant metafield
                variant_metafield = None
                for v_edge in safe_get(product, ['variants', 'edges'], []):
                    v_node = safe_get(v_edge, 'node', {})
                    if safe_get(v_node, 'sku') == sku:
                        variant_metafield = safe_get(v_node, ['metafield', 'value'])
                        break

                products_by_sku[sku] = {
                    'variant': node,
                    'product': product,
                    'metafields': metafields,
                    'edition': variant_metafield
                }
            except Exception as e:
                error_msg = f"Error processing product {sku}: {str(e)}"
                errors.append(error_msg)

        return products_by_sku, errors

    except requests.exceptions.RequestException as e:
        error_msg = f"API request failed: {str(e)}"
        return None, [error_msg]
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        return None, [error_msg]
 
@app.route('/getproduct', methods=['POST', 'OPTIONS'])
def generate_pdf():
    if request.method == 'OPTIONS':
        return '', 204

    try:
        data = request.get_json()
        datasku = data.get("isbn")
        products, errors = fetch_products_by_skus(str(datasku))
        if errors:
            return jsonify({"errors": errors}), 400
        product = products.get(datasku) if products else None
        print(product)
        if not product:
            return jsonify({"error": "Product not found"}), 404
        # Extraction code
        product_title = product["product"]["title"]
        image_url = product["product"]["featuredImage"]["url"] if product["product"].get("featuredImage") else None
        variants = [
            {
          "title": variant["node"]["title"],
          "sku": variant["node"]["sku"],
          "isbn": variant["node"]["sku"],
          "price": variant["node"]["price"],
          "currency": "USD",  # Assuming currency is USD as it's not in the response
          "edition": product["edition"],
            }
            for variant in product["product"]["variants"]["edges"]
        ]

        metafields = product["metafields"]
        subject_raw = metafields.get("custom_subject")
        # Remove brackets and quotes
        subject = subject_raw.strip('[]').replace('"', '').replace("'", '') if subject_raw else None
        # Optional: handle multiple items by splitting
        subject = ", ".join(item.strip() for item in subject.split(',') if item.strip()) if subject else None
        publisher = metafields.get("custom_publisher")
        edition = metafields.get("custom_edition")  # This will be None if not present
        volume = metafields.get("custom_volume")    # This will also be None if not present
        pub_date = metafields.get("custom_publication_date")
        formatted_date = None
        if pub_date:
          try:
            date_obj = datetime.strptime(pub_date, "%Y-%m-%d")
            formatted_date = date_obj.strftime("%B %d, %Y")
          except ValueError:
            formatted_date = pub_date  # Fallback to raw date if parsing fails
        pages = metafields.get("custom_pages")

        # Assuming truncate_html_preserving_tags is a defined function
        about_book = truncate_html_preserving_tags(metafields.get("custom_about_the_book", ""),1100)
        authors = ", ".join(filter(None, [
            metafields.get("custom_author"),
            metafields.get("custom_author2"),
            metafields.get("custom_author3"),
        ]))
        about_author = truncate_html_preserving_tags(metafields.get("custom_about_the_author", ""),900)
        toc = truncate_html_preserving_tags(metafields.get("custom_table_of_contents", ""), 950)

        # Render HTML template
        rendered_html = render_template(
            'flyer_template.html',
            product_title=product_title,
            product_image=image_url,
            product_category=subject,
            publisher=publisher,
            edition=edition,
            volume=volume,
            publishing_date=formatted_date,
            pages=pages,
            variants=variants,
            book_desc=about_book,
            author=authors,
            about_author=about_author,
            toc=toc
        )

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