import os
import requests
import logging
import traceback
from flask import Flask, request, render_template, send_file, jsonify
from flask_cors import CORS
import pdfkit
import streamlit as st
from datetime import datetime
from PyPDF2 import PdfMerger
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO 
from dotenv import load_dotenv
import jinja2
from bs4 import BeautifulSoup
import time
import math

load_dotenv()

# Configuration 
SHOPIFY_DOMAIN = os.getenv('SHOPIFY_DOMAIN')
ADMIN_API_TOKEN = os.getenv('SHOPIFY_ADMIN_API_TOKEN')
API_VERSION = os.getenv('SHOPIFY_API_VERSION', '2025-04')
WKHTMLTOPDF_PATH = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"

# Configure pdfkit
config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)

# Jinja2 setup
template_loader = jinja2.FileSystemLoader(searchpath='./templates')
template_env = jinja2.Environment(loader=template_loader)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('flyer_generator.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
MAX_API_BATCH_SIZE = 100  # Shopify's GraphQL limit
MAX_WORKERS = 10  # Optimal balance between speed and resource usage
MAX_RETRIES = 3  # For API calls
RETRY_DELAY = 2  # Seconds between retries

def safe_get(dictionary, keys, default=''):
    """Safely get nested dictionary keys with error handling"""
    if not isinstance(keys, list):
        keys = [keys]
    try:
        for key in keys:
            dictionary = dictionary.get(key, {}) if isinstance(dictionary, dict) else default
            if dictionary is None:
                return default
        return dictionary or default
    except (AttributeError, TypeError):
        return default

def truncate_html_preserving_tags(html_content, char_limit):
    """Truncate HTML content while preserving tag structure"""
    if not html_content or not isinstance(html_content, str):
        return ''
    
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        total_chars = 0

        def truncate_node(node):
            nonlocal total_chars
            if node.name is None:  # Text node
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
    except Exception as e:
        logger.error(f"HTML truncation failed: {str(e)}")
        return html_content[:char_limit] if html_content else ''
    
def calculate_optimal_content_distribution(about_book, about_author, max_total_chars=2000):
    """Dynamically adjust space allocation between book and author sections
    based on their content length.
    """
    # Calculate initial lengths
    book_len = len(about_book) if about_book else 0
    author_len = len(about_author) if about_author else 0
    total_len = book_len + author_len
    
    # If total content fits within limits, return as-is
    if total_len <= max_total_chars:
        return about_book, about_author
    
    # Calculate ideal ratios based on content length
    if book_len == 0:
        return '', truncate_html_preserving_tags(about_author, max_total_chars)
    if author_len == 0:
        return truncate_html_preserving_tags(about_book, max_total_chars), ''
    
    # Calculate dynamic ratio (minimum 30% for each section)
    book_ratio = max(0.3, min(0.7, book_len / total_len))
    author_ratio = 1 - book_ratio
    
    # Calculate allocated characters
    book_chars = int(max_total_chars * book_ratio)
    author_chars = max_total_chars - book_chars
    
    # Truncate content
    truncated_book = truncate_html_preserving_tags(about_book, book_chars)
    truncated_author = truncate_html_preserving_tags(about_author, author_chars)
    
    return truncated_book, truncated_author

def fetch_products_batch(skus, attempt=1):
    """Fetch a batch of products with retry logic"""
    headers = {
        "X-Shopify-Access-Token": ADMIN_API_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    sku_query = ' OR '.join(f'sku:{sku}' for sku in skus)
    query = """
    query GetProductsBySkus($first: Int!, $query: String!) {
      productVariants(first: $first, query: $query) {
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
        "first": len(skus),
        "query": sku_query
    }

    try:
        response = requests.post(
            f"https://{SHOPIFY_DOMAIN}/admin/api/{API_VERSION}/graphql.json",
            json={'query': query, 'variables': variables},
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        
        data = response.json()
        
        if safe_get(data, 'errors'):
            errors = [err.get('message', 'Unknown GraphQL error') for err in safe_get(data, 'errors', [])]
            logger.error(f"GraphQL Errors: {errors}")
            if attempt <= MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
                return fetch_products_batch(skus, attempt + 1)
            return None, errors
            
        edges = safe_get(data, ['data', 'productVariants', 'edges'], [])
        
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

                print(products_by_sku)
            except Exception as e:
                error_msg = f"Error processing product {sku}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)

        return products_by_sku, errors

    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed (attempt {attempt}): {str(e)}")
        
        if attempt <= MAX_RETRIES:
            time.sleep(RETRY_DELAY * attempt)
            return fetch_products_batch(skus, attempt + 1)
        return None, [f"API request failed after {MAX_RETRIES} attempts: {str(e)}"]

    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(error_msg)
        return None, [error_msg]
    

def fetch_all_products(skus):
    """Fetch all products in batches"""
    products_by_sku = {}
    all_errors = []
    
    # Split SKUs into batches
    batches = [skus[i:i + MAX_API_BATCH_SIZE] for i in range(0, len(skus), MAX_API_BATCH_SIZE)]
    
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(batches))) as executor:
        futures = {executor.submit(fetch_products_batch, batch): batch for batch in batches}
        
        for future in as_completed(futures):
            batch_result, batch_errors = future.result()
            if batch_result:
                products_by_sku.update(batch_result)
            if batch_errors:
                all_errors.extend(batch_errors)
    
    return products_by_sku, all_errors


def prepare_template_context(product_data):
    """Prepare template context with null checks"""
    if not product_data:
        return {}, "No product data provided"
    
    try:
        product = safe_get(product_data, 'product', {})
        variant = safe_get(product_data, 'variant', {})
        metafields = safe_get(product_data, 'metafields', {})
        
        # Process variants
        variants = []
        variant_errors = []
        for edge in safe_get(product, ['variants', 'edges'], []):
            try:
                v_node = safe_get(edge, 'node', {})
                variants.append({
                    'isbn': safe_get(v_node, 'sku', ''),
                    'title': safe_get(v_node, 'title', ''),
                    'price': safe_get(v_node, 'price', '0.00'),
                    'edition': safe_get(v_node, ['metafield', 'value'], '')
                })
            except Exception as e:
                variant_errors.append(f"Variant error: {str(e)}")
        
        if variant_errors:
            logger.warning(f"Variant processing errors: {variant_errors}")
        
        # Process subject field
        subject_raw = safe_get(metafields, 'custom_subject', '')
        subject = subject_raw.strip('[]').replace('"', '').replace("'", '')
        subject = ", ".join(item.strip() for item in subject.split(',') if item.strip())

        # Get raw about the book and author content
        raw_book_desc = safe_get(metafields, 'custom_about_the_book', '')
        raw_about_author = safe_get(metafields, 'custom_about_the_author', '')

        # Dynamically balance content
        book_desc, about_author = calculate_optimal_content_distribution(
            raw_book_desc, 
            raw_about_author,
            max_total_chars=2000  # Adjust based on your layout needs
        )
        
        context = {
            'product_title': safe_get(product, 'title', 'Untitled Product'),
            'product_image': safe_get(product, ['featuredImage', 'url'], ''),
            'product_category': safe_get(product, 'productType', ''),
            'publisher_imprint': safe_get(metafields, 'custom_imprint', ''),
            'publishing_date': safe_get(metafields, 'custom_publication_date', ''),
            'pages': safe_get(metafields, 'custom_pages', ''),
            'author': ", ".join(filter(None, [
                safe_get(metafields, 'custom_author'),
                safe_get(metafields, 'custom_author'),
                safe_get(metafields, 'custom_author'),
            ])),
            'book_desc':book_desc,
            'about_author': about_author,
            'toc': truncate_html_preserving_tags(
                safe_get(metafields, 'custom_table_of_contents', ''), 
                900
            ),
            'publisher': safe_get(metafields, 'custom_publisher', ''),
            'subject': subject,
            'volume': safe_get(metafields, 'custom_volume', ''),
            'edition': safe_get(product_data, 'edition', ''),
            'isbn': safe_get(variant, 'sku', ''),
            'price': safe_get(variant, 'price', '0.00'),
            'variants': variants,
            'current_year': datetime.now().year
        }
        
        return context, None
        
    except Exception as e:
        error_msg = f"Error preparing template: {str(e)}"
        logger.error(error_msg)
        return {}, error_msg

def generate_pdf(html_content):
    """Generate PDF with error handling"""
    if not html_content:
        return None, "No HTML content provided"
    
    try:
        options = {
            'page-size': 'A4',
            'margin-top': '0mm',
            'margin-bottom': '0mm',
            'encoding': 'UTF-8',
            'print-media-type': '',
            'background': '',
            'no-outline': None,
            'enable-local-file-access': None,
            'quiet': '',
            'disable-smart-shrinking': None,
            'print-media-type': '',
            'custom-header': [
                ('Accept-Encoding', 'gzip')
            ],
            'no-stop-slow-scripts': None,
            'enable-javascript': None,
            'javascript-delay': '1000'
                }

       
        pdf_bytes = pdfkit.from_string(html_content, False, options=options, configuration=config)
        return pdf_bytes, None
    except Exception as e:
        error_msg = f"PDF generation failed: {str(e)}"
        logger.error(error_msg)
        return None, error_msg

def generate_single_flyer(sku, products_data):
    """Generate a single flyer with complete error handling"""
    try:
        if not sku:
            return None, "No SKU provided"
        
        if sku not in products_data:
            return None, f"Product data not found for SKU: {sku}"
        
        # Prepare template context
        context, context_error = prepare_template_context(products_data[sku])
        if context_error:
            return None, context_error
        
        # Render template
        try:
            template = template_env.get_template('flyer_template.html')
            html_content = template.render(**context)
        except Exception as e:
            error_msg = f"Template rendering failed: {str(e)}"
            logger.error(error_msg)
            return None, error_msg
        
        # Generate PDF
        pdf_bytes, pdf_error = generate_pdf(html_content)
        if pdf_error:
            return None, pdf_error
        
        return pdf_bytes, None
        
    except Exception as e:
        error_msg = f"Error generating flyer for {sku}: {str(e)}"
        logger.error(error_msg)
        return None, error_msg

def main():
    st.set_page_config(page_title="Bulk Flyer Generator", layout="wide")
    st.title("📚 Bulk Product Flyer Generator")
    
    # Input section
    with st.expander("📥 Input Options", expanded=True):
        input_method = st.radio("Input method:", 
                              ["Text input", "File upload"],
                              horizontal=True)
        
        skus = []
        if input_method == "Text input":
            sku_text = st.text_area("Enter ISBNs/SKUs (one per line or comma separated):", 
                                  height=150)
            if sku_text:
                skus = [s.strip() for line in sku_text.split('\n') 
                       for s in line.split(',') if s.strip()]
        else:
            uploaded_file = st.file_uploader("Upload a text file with ISBNs/SKUs", 
                                           type=["txt", "csv"])
            if uploaded_file:
                try:
                    file_contents = uploaded_file.getvalue().decode("utf-8")
                    skus = [s.strip() for line in file_contents.split('\n') 
                           for s in line.split(',') if s.strip()]
                except Exception as e:
                    st.error(f"Error reading file: {str(e)}")
                    return
    
    if not skus:
        st.warning("Please enter at least one valid ISBN/SKU")
        return
    
    # Options section
    with st.expander("⚙️ Generation Options", expanded=True):
        output_format = st.radio("Output format:", 
                                ["Single merged PDF", "Individual PDF files"],
                                index=0)
        
        max_workers = st.slider("Parallel processing threads:", 
                               min_value=1, max_value=10, value=4)
    
    if st.button("🚀 Generate Flyers", type="primary"):
        if len(skus) > 1000:
            st.warning("Processing large batch (1000+ SKUs), this may take several minutes...")
        
        st.info(f"Preparing to generate {len(skus)} flyers...")
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        results_placeholder = st.empty()
        
        # Track results
        generated_pdfs = {}
        failed_skus = []
        processed_count = 0
        
        # Step 1: Fetch all product data first (batched)
        with st.spinner("Fetching product data from Shopify..."):
            products_data, fetch_errors = fetch_all_products(skus)
            if fetch_errors:
                st.warning(f"Encountered {len(fetch_errors)} errors while fetching products")
        
        # Step 2: Generate PDFs in parallel
        with st.spinner("Generating flyers..."):
            with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, max_workers)) as executor:
                futures = {
                    executor.submit(generate_single_flyer, sku, products_data): sku 
                    for sku in skus if sku in products_data
                }
                
                for future in as_completed(futures):
                    sku = futures[future]
                    try:
                        pdf_bytes, error = future.result()
                        if pdf_bytes:
                            generated_pdfs[sku] = pdf_bytes
                        if error:
                            failed_skus.append(f"{sku}: {error}")
                    except Exception as e:
                        failed_skus.append(f"{sku}: {str(e)}")
                    
                    processed_count += 1
                    progress = processed_count / len(skus)
                    progress_bar.progress(min(progress, 1.0))
                    status_text.text(
                        f"Processed {processed_count}/{len(skus)} SKUs | "
                        f"Success: {len(generated_pdfs)} | "
                        f"Failed: {len(failed_skus)}"
                    )
        
        progress_bar.empty()
        
        # Display results
        with results_placeholder.container():
            if generated_pdfs:
                st.success(f"Successfully generated {len(generated_pdfs)} flyers!")
                
                if output_format == "Single merged PDF":
                    with st.spinner("Merging PDFs..."):
                        try:
                            merger = PdfMerger()
                            for pdf_bytes in generated_pdfs.values():
                                merger.append(BytesIO(pdf_bytes))
                            
                            merged_pdf = BytesIO()
                            merger.write(merged_pdf)
                            merged_pdf.seek(0)
                            
                            st.download_button(
                                label="⬇️ Download Merged PDF",
                                data=merged_pdf,
                                file_name="merged_flyers.pdf",
                                mime="application/pdf"
                            )
                        except Exception as e:
                            st.error(f"Failed to merge PDFs: {str(e)}")
                else:
                    with st.spinner("Creating ZIP archive..."):
                        try:
                            import zipfile
                            zip_buffer = BytesIO()
                            with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
                                for sku, pdf_bytes in generated_pdfs.items():
                                    zip_file.writestr(f"flyer_{sku}.pdf", pdf_bytes)
                            zip_buffer.seek(0)
                            
                            st.download_button(
                                label="⬇️ Download All Flyers (ZIP)",
                                data=zip_buffer,
                                file_name="flyers.zip",
                                mime="application/zip"
                            )
                        except Exception as e:
                            st.error(f"Failed to create ZIP: {str(e)}")
            
            if failed_skus:
                with st.expander("⚠️ Failed SKUs", expanded=False):
                    st.warning(f"{len(failed_skus)} flyers failed to generate:")
                    st.code("\n".join(failed_skus))

if __name__ == "__main__":
    main()