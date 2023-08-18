from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, RedirectResponse
import requests
import mysql.connector
from mysql.connector import Error
from fuzzywuzzy import fuzz
from transformers import pipeline

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Intent classification API
classification_pipe = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")
candidate_labels = [
    "account",
    "home",
    "products",
    "cart", "product's price high to low","product's price low to high", "add to cart",
    "remove from cart","product's details information"
]

# Establish a connection to the MySQL database
def create_connection():
    try:
        connection = mysql.connector.connect(
            host='localhost',
            database='webgpt',
            user='root',
            password='password'
        )

        return connection
    except Error as e:
        print(f"Error connecting to MySQL database: {e}")
        return None

# Retrieve product data from the MySQL database
def get_products():
    try:
        connection = create_connection()
        if connection is not None:
            cursor = connection.cursor()
            cursor.execute("SELECT id, name, price FROM products")
            products = cursor.fetchall()
            cursor.close()
            return products
    except Error as e:
        print(f"Error retrieving products from MySQL database: {e}")
    finally:
        if connection is not None:
            connection.close()
    return []

# Retrieve a random subset of products from the MySQL database
def get_random_products(num_products=3):
    connection = create_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM products ORDER BY RAND() LIMIT %s", (num_products,))
    random_products = cursor.fetchall()
    cursor.close()
    connection.close()
    return random_products

# Modify the get_product function to query the product by ID from the MySQL database
def get_product(product_id: int):
    try:
        connection = create_connection()
        if connection is not None:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
            product = cursor.fetchone()
            cursor.close()
            if product is not None:
                return {
                    "id": product[0],
                    "name": product[1],
                    "price": product[2],
                    "description": product[3]
                }
    except Error as e:
        print(f"Error retrieving product from MySQL database: {e}")
    finally:
        if connection is not None:
            connection.close()
    return None

def get_cart():
    try:
        connection = create_connection()
        if connection is not None:
            cursor = connection.cursor()
            cursor.execute("SELECT c.product_id, p.name, p.price, c.quantity FROM cart c JOIN products p ON c.product_id = p.id")
            cart_items = cursor.fetchall()
            cursor.close()
            connection.close()

            cart = []
            for product_id, name, price, quantity in cart_items:
                cart.append({
                    "product": {
                        "id": product_id,
                        "name": name,
                        "price": price,
                    },
                    "quantity": quantity
                })

            return cart
    except Error as e:
        print(f"Error retrieving cart items from MySQL database: {e}")
    return []



# Home page
@app.route("/", methods=["GET", "POST"])
async def home(request: Request):
    random_products = get_random_products(6)
    return templates.TemplateResponse("home.html", {"request": request, "random_products": random_products})

# Product list page
@app.get("/products")
def get_product_list(request: Request, sort: str = ""):
    products = get_products()

    if sort == "price_asc":
        sorted_products = sorted(products, key=lambda x: x[2])
    elif sort == "price_desc":
        sorted_products = sorted(products, key=lambda x: x[2], reverse=True)
    else:
        sorted_products = products

    # Retrieve the product details and add them to the sorted_products list
    product_details = []
    for product in sorted_products:
        product_id = product[0]
        product_detail = get_product(product_id)
        if product_detail:
            product_details.append(product_detail)

    return templates.TemplateResponse("products.html", {"request": request, "products": product_details})


# POST request for product list page
@app.post("/products")
def post_product_list(request: Request):
    return get_product_list(request)

@app.post("/display_sorted_products")
def display_sorted_products(request: Request, sort: str = "price_desc"):
    products = get_products()

    if sort == "price_asc":
        sorted_products = sorted(products, key=lambda x: x[2])
    elif sort == "price_desc":
        sorted_products = sorted(products, key=lambda x: x[2], reverse=True)
    else:
        sorted_products = products

    # Generate the list of product links
    product_links = [
        {
            "name": product[1],
            "price": product[2],
            "url": f"/products/{product[0]}"
        }
        for product in sorted_products
    ]

    return templates.TemplateResponse("popup.html", {"request": request, "products": product_links})

@app.get("/products/{product_id}")
def get_product_detail(request: Request, product_id: int):
    product = get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return templates.TemplateResponse("product_detail.html", {"request": request, "product": product})

@app.post("/products/{product_id}")
def post_product_detail(request: Request, product_id: int):
    return get_product_detail(request, product_id)

# Cart page
# Cart page
@app.route("/cart", methods=["GET", "POST"])
def view_cart(request: Request):
    # Retrieve the cart items and their quantities from the cart table
    cart = get_cart()

    return templates.TemplateResponse("cart.html", {"request": request, "cart": cart})


# Add product to cart
@app.post("/add_to_cart", response_class=JSONResponse)
async def add_to_cart(request: Request):
    data = await request.json()
    product_id = data.get("product_id")
    if product_id is None:
        raise HTTPException(status_code=400, detail="Product ID not provided")

    # Check if the product exists in the products table
    product = get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Add the product to the cart or update the quantity
    connection = create_connection()
    cursor = connection.cursor()
    try:
        # If the product is already in the cart, update the quantity
        cursor.execute("INSERT INTO cart (product_id, quantity) VALUES (%s, 1) ON DUPLICATE KEY UPDATE quantity = quantity + 1", (product_id,))
        connection.commit()
    except mysql.connector.IntegrityError as e:
        # If the product is already in the cart, update the quantity
        cursor.execute("UPDATE cart SET quantity = quantity + 1 WHERE product_id = %s", (product_id,))
        connection.commit()

    cursor.close()
    connection.close()

    return {"message": f"Product with ID {product_id} added to cart"}

# Modify the remove_from_cart function to handle quantity updates
@app.post("/remove_from_cart", response_class=JSONResponse)
async def remove_from_cart(request: Request):
    data = await request.json()
    product_id = data.get("product_id")
    if product_id is None:
        raise HTTPException(status_code=400, detail="Product ID not provided")

    connection = create_connection()
    cursor = connection.cursor()

    # Check if the product is in the cart
    cursor.execute("SELECT quantity FROM cart WHERE product_id = %s", (product_id,))
    cart_item = cursor.fetchone()

    if cart_item:
        quantity = cart_item[0]
        if quantity > 1:
            # If quantity is more than 1, update the quantity in the cart
            cursor.execute("UPDATE cart SET quantity = %s WHERE product_id = %s", (quantity - 1, product_id))
        else:
            # If quantity is 1, remove the product from the cart
            cursor.execute("DELETE FROM cart WHERE product_id = %s", (product_id,))

        connection.commit()

    cursor.close()
    connection.close()

    return {"message": "Product removed from cart"}

@app.route("/account", methods=["GET", "POST"])
def account(request: Request):
    return templates.TemplateResponse("account.html", {"request": request})


# Process instruction
@app.post("/process_instruction", response_class=RedirectResponse)
async def process_instruction(instruction: str = Form(...)):
    classification_result = classification_pipe(instruction, candidate_labels)
    max_index = classification_result['scores'].index(max(classification_result['scores']))
    intent = classification_result['labels'][max_index]
    print("Intent:", intent)

    if intent == "account":
        # Redirect to the account page
        return RedirectResponse(url="/account")
    elif intent == "home":
        # Redirect to the home page
        return RedirectResponse(url="/")
    elif intent == "products":
        # Redirect to the product list page
        return RedirectResponse(url="/products")
    elif intent == "cart":
        # Redirect to the cart page
        return RedirectResponse(url="/cart")
    elif intent == "product's price high to low":
        # Display sorted products in a popup box (descending order)
        return RedirectResponse(url="/display_sorted_products?sort=price_desc")
    elif intent == "product's price low to high":
        # Display sorted products in a popup box (ascending order)
        return RedirectResponse(url="/display_sorted_products?sort=price_asc")
    elif intent == "add to cart":
        # Extract the product ID from the instruction
        product_id = extract_product_id(instruction)
        if product_id is None:
            raise HTTPException(status_code=400, detail="Product ID not provided")

        # Check if the product exists in the products table
        product = get_product(product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        connection = create_connection()
        cursor = connection.cursor()

        # Check if the product is already in the cart
        cursor.execute("SELECT quantity FROM cart WHERE product_id = %s", (product_id,))
        cart_item = cursor.fetchone()

        if cart_item:
            # If the product is in the cart, increment the quantity
            quantity = cart_item[0] + 1
            cursor.execute("UPDATE cart SET quantity = %s WHERE product_id = %s", (quantity, product_id))
        else:
            # If the product is not in the cart, add it to the cart with quantity 1
            cursor.execute("INSERT INTO cart (product_id, quantity) VALUES (%s, 1)", (product_id,))

        connection.commit()
        cursor.close()
        connection.close()

        return RedirectResponse(url="/cart", status_code=307)

    elif intent == "remove from cart":
        # Extract the product ID from the instruction
        product_id = extract_product_id(instruction)
        if product_id is None:
            raise HTTPException(status_code=400, detail="Product ID not provided")

        connection = create_connection()
        cursor = connection.cursor()

        # Check if the product is in the cart
        cursor.execute("SELECT quantity FROM cart WHERE product_id = %s", (product_id,))
        cart_item = cursor.fetchone()

        if cart_item:
            # If the product is in the cart and its quantity is more than 1, decrement the quantity
            if cart_item[0] > 1:
                quantity = cart_item[0] - 1
                cursor.execute("UPDATE cart SET quantity = %s WHERE product_id = %s", (quantity, product_id))
            else:
                # If the product is in the cart and its quantity is 1, remove it from the cart
                cursor.execute("DELETE FROM cart WHERE product_id = %s", (product_id,))
        else:
            raise HTTPException(status_code=404, detail="Product not found in the cart")

        connection.commit()
        cursor.close()
        connection.close()

        return RedirectResponse(url="/cart", status_code=307)
    elif intent == "product's details information":
        # Extract the product name from the instruction
        product_id = extract_product_id(instruction)
        if product_id is None:
            raise HTTPException(status_code=400, detail="Product name not provided")
        # Redirect to the individual product page
        return RedirectResponse(url=f"/products/{product_id}")
    else:
        raise HTTPException(status_code=400, detail="Unrecognized intent")

def extract_product_id(instruction: str):
    try:
        connection = create_connection()
        if connection is not None:
            cursor = connection.cursor()
            cursor.execute("SELECT id, name FROM products")
            products_data = cursor.fetchall()
            cursor.close()
    except Error as e:
        print(f"Error retrieving products data from MySQL database: {e}")
    finally:
        if connection is not None:
            connection.close()

    best_match_ratio = 0
    best_match_product_id = None

    for product_id, product_name in products_data:
        similarity_ratio = fuzz.partial_ratio(product_name.lower(), instruction.lower())
        if similarity_ratio > best_match_ratio:
            best_match_ratio = similarity_ratio
            best_match_product_id = product_id

    # Adjust the threshold as per your requirement
    if best_match_ratio > 70:
        return best_match_product_id

    return None



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
