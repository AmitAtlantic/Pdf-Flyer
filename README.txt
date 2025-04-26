// Insert This js code on product.template file in shopify

<script>
  {% assign authors = "" %}
{% if product.metafields.custom.author %}
  {% assign authors = authors | append: product.metafields.custom.author %}
{% endif %}
{% if product.metafields.custom.author2 %}
  {% if authors != "" %}
    {% assign authors = authors | append: ", " %}
  {% endif %}
  {% assign authors = authors | append: product.metafields.custom.author2 %}
{% endif %}
{% if product.metafields.custom.author3 %}
  {% if authors != "" %}
    {% assign authors = authors | append: ", " %}
  {% endif %}
  {% assign authors = authors | append: product.metafields.custom.author3 %}
{% endif %}

const payload = {
  product_title: "{{ product.title }}",
  product_image: "{{ product.featured_image | img_url: 'master' | prepend: 'https:'  }}",
  edition: "{{ product.selected_or_first_available_variant.metafields.custom.edition }}",
  volume: "{{ product.metafields.custom.volume }}",
  product_category: "{{ product.metafields.custom.subject.value }}",
  publisher: "{{ product.metafields.custom.publisher.value }}",
  publishing_date: "{{ product.metafields.custom.publication_date | date: '%B %d, %Y' }}",
  pages: "{{ product.metafields.custom.pages.value }}",
  author: "{{ authors }}",
      variants: [
      {% for variant in product.variants %}
        {
          title: "{{ variant.title | escape }}",
          sku: "{{ variant.sku | escape }}",
          isbn: "{{ variant.barcode | escape }}",
          price: "{{ variant.price | money_without_currency }}"
        }{% unless forloop.last %},{% endunless %}
      {% endfor %}
    ],
  book_desc: `{{ product.metafields.custom.about_the_book | metafield_tag }}`,
  about_author: `{{ product.metafields.custom.about_the_author | metafield_tag }}`,
  toc: `{{ product.metafields.custom.table_of_contents }}`
};
console.log('PAyload', payload)

document.getElementById('flyer_download').addEventListener('click', () => {
  document.querySelector('.flyer_text').style.display='none';
  document.querySelector('.flyer_icon').style.display='block';
    fetch('https://bc0f-59-144-160-111.ngrok-free.app/getproduct', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
    })
    .then(response => {
        if (!response.ok) throw new Error('Network response was not ok');
        return response.blob();
    })
    .then(blob => {
        document.querySelector('.flyer_text').style.display='block';
        document.querySelector('.flyer_icon').style.display='none';
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${payload.product_title || 'flyer'}_flyer.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
    })
    .catch(error => console.error('Error downloading PDF:', error));
});

</script>