from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
from bson.objectid import ObjectId
from pymongo import MongoClient
from datetime import datetime
import os
from werkzeug.utils import secure_filename
# --- CẤU HÌNH ỨNG DỤNG ---

UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.secret_key = "super_secret_key"

# --- KẾT NỐI MONGODB ---
client = MongoClient("mongodb://localhost:27017")
db = client["coffee_shop"]  # database

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# --- MIDDLEWARE ---
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Bạn không có quyền truy cập!", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapper

# --- LOGIN ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = db.users.find_one({"username": username, "password": password})
        if user:
            session["user_id"] = str(user["_id"])
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))
        else:
            flash("Sai tài khoản hoặc mật khẩu!", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Đã đăng xuất!", "info")
    return redirect(url_for("login"))

@app.route("/")
@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")

# --- USERS ---
@app.route("/users")
@admin_required
def users():
    data = list(db.users.find())
    return render_template("users.html", users=data)

@app.route("/users/add", methods=["GET", "POST"])
@admin_required
def add_user():
    if request.method == "POST":
        db.users.insert_one({
            "username": request.form["username"],
            "password": request.form["password"],
            "full_name": request.form["full_name"],
            "role": request.form["role"],
            "created_at": datetime.utcnow()
        })
        return redirect(url_for("users"))
    return render_template("user_form.html", action="Thêm")

@app.route("/users/edit/<id>", methods=["GET", "POST"])
def edit_user(id):
    user = db.users.find_one({"_id": ObjectId(id)})
    if request.method == "POST":
        name = request.form["name"]
        role = request.form["role"]
        db.users.update_one(
            {"_id": ObjectId(id)},
            {"$set": {"name": name, "role": role}}
        )
        return redirect(url_for("users"))
    return render_template("edit_user.html", user=user)

@app.route("/users/delete/<id>")
def delete_user(id):
    db.users.delete_one({"_id": ObjectId(id)})
    return redirect(url_for("users"))

# --- PRODUCTS ---
@app.route("/products")
@login_required
def products():
    data = list(db.products.find())
    return render_template("products.html", products=data)

@app.route("/products/add", methods=["GET", "POST"])
@admin_required
def add_product():
    if request.method == "POST":
        file = request.files.get("image")
        image_path = None
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            image_path = f"/static/uploads/{filename}"
        db.products.insert_one({
            "name": request.form["name"],
            "price": float(request.form["price"]),
            "description": request.form["description"],
            "image": image_path
        })
        return redirect(url_for("products"))
    return render_template("product_form.html", action="Thêm")

@app.route("/products/edit/<id>", methods=["GET", "POST"])
def edit_product(id):
    product = db.products.find_one({"_id": ObjectId(id)})
    if request.method == "POST":
        name = request.form["name"]
        price = float(request.form["price"])
        category = request.form["category"]
        db.products.update_one(
            {"_id": ObjectId(id)},
            {"$set": {"name": name, "price": price, "category": category}}
        )
        return redirect(url_for("products"))
    return render_template("edit_product.html", product=product)

@app.route("/products/delete/<id>", methods=["GET"])
def delete_product(id):
    db.products.delete_one({"_id": ObjectId(id)})
    return redirect(url_for("products"))

# --- POS ---
@app.route("/pos")
@login_required
def pos():
    tables = list(db.tables.find())
    for t in tables:
        open_order = db.orders.find_one({"table_id": t["_id"], "status": "Chưa thanh toán"})
        t["open_cnt"] = 1 if open_order else 0
    return render_template("pos.html", tables=tables)

@app.route("/pos/table/<table_id>")
@login_required
def pos_table(table_id):
    table = db.tables.find_one({"_id": ObjectId(table_id)})
    
    order = db.orders.find_one({"table_id": table["_id"], "status": "Chưa thanh toán"})
    if not order:
        order_id = db.orders.insert_one({
            "table_id": table["_id"],
            "user_id": ObjectId(session["user_id"]),
            "items": [],
            "total": 0,
            "status": "Chưa thanh toán",
            "created_at": datetime.utcnow()
        }).inserted_id
        order = db.orders.find_one({"_id": order_id})
        db.tables.update_one({"_id": table["_id"]}, {"$set": {"status": "Đang dùng"}})
    products = list(db.products.find())
    total = sum(i["quantity"] * i["price"] for i in order["items"])
    return render_template("pos_table.html", table=table, order=order, products=products, items=order["items"], total=total)

@app.route("/pos/order/<table_id>", methods=["POST"])
@login_required
def pos_order(table_id):
    product_id = ObjectId(request.form["product_id"])
    quantity = int(request.form["quantity"])
    product = db.products.find_one({"_id": product_id})
    order = db.orders.find_one({"table_id": ObjectId(table_id), "status": "Chưa thanh toán"})
    if not order:
        order_id = db.orders.insert_one({
            "table_id": ObjectId(table_id),
            "user_id": ObjectId(session["user_id"]),
            "items": [],
            "total": 0,
            "status": "Chưa thanh toán",
            "created_at": datetime.utcnow()
        }).inserted_id
        order = db.orders.find_one({"_id": order_id})
    
    db.orders.update_one({"_id": order["_id"]}, {
        "$push": {"items": {
            "product_id": product["_id"],
            "name": product["name"],
            "quantity": quantity,
            "price": product["price"]
        }}
    })
    order = db.orders.find_one({"_id": order["_id"]})
    total = sum(i["quantity"] * i["price"] for i in order["items"])
    db.orders.update_one({"_id": order["_id"]}, {"$set": {"total": total}})
    flash("Đã thêm vào order!", "success")
    return redirect(url_for("pos_table", table_id=table_id))

# --- THANH TOÁN & ĐƠN HÀNG ---
@app.route("/orders")
@login_required
def orders():
    data = list(db.orders.find())
    for o in data:
        o["_id"] = str(o["_id"])
    return render_template("orders.html", orders=data)

@app.route("/orders/pay/<order_id>")
@login_required
def pay_order(order_id):
    order = db.orders.find_one({"_id": ObjectId(order_id)})
    db.orders.update_one({"_id": order["_id"]}, {"$set": {"status": "Đã thanh toán"}})
    db.tables.update_one({"_id": order["table_id"]}, {"$set": {"status": "Trống"}})
    flash("Thanh toán thành công!", "success")
    return redirect(url_for("pos"))


@app.route("/orders/print/<order_id>")
@login_required
def order_print(order_id):
    # kiểm tra order_id hợp lệ
    try:
        order = db.orders.find_one({"_id": ObjectId(order_id)})
    except Exception:
        return "ID hóa đơn không hợp lệ!", 400

    if not order:
        return "Không tìm thấy đơn hàng", 404

    # đảm bảo có items
    items = order.get("items", []) or []

    # chuẩn hóa từng item: đảm bảo price, quantity là số, tính subtotal
    safe_items = []
    for it in items:
        # lấy giá trị an toàn
        name = it.get("name", "Không tên")
        try:
            price = float(it.get("price", 0) or 0)
        except Exception:
            price = 0.0
        try:
            qty = int(it.get("quantity", 0) or 0)
        except Exception:
            qty = 0
        subtotal = qty * price

        safe_items.append({
            "name": name,
            "price": price,
            "quantity": qty,
            "subtotal": subtotal
        })

    # tính tổng (an toàn)
    total = sum(i["subtotal"] for i in safe_items)

    # chuyển các ObjectId & thời gian sang chuỗi để template hiển thị
    order_display = {}
    order_display["_id"] = str(order.get("_id"))
    order_display["id"] = str(order.get("_id"))[-6:]  # nếu muốn mã ngắn
    order_display["total"] = total
    order_display["status"] = order.get("status", "N/A")
    # lấy tên bàn và tên nhân viên nếu có
    order_display["table_name"] = order.get("table_name", order.get("table_id", "N/A"))
    # lấy tên nhân viên lưu trong order (nếu lưu user_id thì truy vấn thêm)
    order_display["full_name"] = order.get("full_name", session.get("username", ""))
    # created_at - format nếu có
    created_at = order.get("created_at")
    if isinstance(created_at, datetime):
        order_display["created_at"] = created_at.strftime("%d/%m/%Y %H:%M:%S")
    else:
        order_display["created_at"] = str(created_at) if created_at else ""

    return render_template("order_print.html",
                           order=order_display,
                           items=safe_items)


@app.route("/orders/delete/<order_id>")
@login_required
def delete_order(order_id):
    db.orders.delete_one({"_id": ObjectId(order_id)})
    flash("Đã xóa đơn hàng!", "info")
    return redirect(url_for("orders"))

@app.route("/orders/<order_id>")
@app.route("/orders/<order_id>")
@login_required
def order_detail(order_id):
    try:
        order = db.orders.find_one({"_id": ObjectId(order_id)})
    except:
        return "ID hóa đơn không hợp lệ!", 400

    if not order:
        return "Không tìm thấy đơn hàng", 404

    # Lấy danh sách sản phẩm trong hóa đơn
    items = order.get("items", [])

    # Chuyển ObjectId sang string để hiển thị
    order["_id"] = str(order["_id"])
    for item in items:
        if "_id" in item:
            item["_id"] = str(item["_id"])

    total = sum(i["quantity"] * i["price"] for i in items)

    return render_template("order_detail.html", order=order, items=items, total=total)
from datetime import datetime
from bson.objectid import ObjectId
from flask import request, render_template

@app.route('/reports', methods=["GET", "POST"])
def reports():

    # ========= 1. Lấy dữ liệu lọc ngày =========
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")

    match_query = {}
    if start_date and end_date:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        end = end.replace(hour=23, minute=59, second=59)

        match_query = {"created_at": {"$gte": start, "$lte": end}}

    # ========= 2. Doanh thu theo NGÀY =========
    pipeline_day = [
        {"$match": match_query},
        {
            "$group": {
                "_id": {"$dateToString": {"date": "$created_at", "format": "%Y-%m-%d"}},
                "doanh_thu": {"$sum": "$total"},
                "so_hoa_don": {"$count": {}}
            }
        },
        {"$sort": {"_id": 1}}
    ]

    rs_day = list(db.orders.aggregate(pipeline_day))
    data_day = [
        {"ngay": r["_id"], "doanh_thu": r["doanh_thu"], "so_hoa_don": r["so_hoa_don"]}
        for r in rs_day
    ]

    labels_day = [d["ngay"] for d in data_day]
    values_day = [d["doanh_thu"] for d in data_day]

    # ========= 3. Doanh thu theo THÁNG =========
    pipeline_month = [
        {"$match": match_query},
        {
            "$group": {
                "_id": {"$dateToString": {"date": "$created_at", "format": "%Y-%m"}},
                "doanh_thu": {"$sum": "$total"}
            }
        },
        {"$sort": {"_id": 1}}
    ]

    rs_month = list(db.orders.aggregate(pipeline_month))
    labels_month = [r["_id"] for r in rs_month]
    values_month = [r["doanh_thu"] for r in rs_month]

    # ========= 4. TOP SẢN PHẨM BÁN CHẠY =========
    pipeline_top = [
        {"$match": match_query},
        {"$unwind": "$items"},
        {
            "$group": {
                "_id": "$items.product_name",
                "so_luong": {"$sum": "$items.quantity"}
            }
        },
        {"$sort": {"so_luong": -1}},
        {"$limit": 10}
    ]

    rs_top = list(db.orders.aggregate(pipeline_top))
    top_labels = [r["_id"] for r in rs_top]
    top_values = [r["so_luong"] for r in rs_top]

    # ========= 5. Tổng số hóa đơn =========
    tong_hoa_don = db.orders.count_documents(match_query)

    # ========= 6. Tổng doanh thu tổng hợp =========
    tong_doanh_thu = sum(d["doanh_thu"] for d in data_day)

    return render_template(
        "reports.html",
        data_day=data_day,
        labels_day=labels_day,
        values_day=values_day,
        labels_month=labels_month,
        values_month=values_month,
        top_labels=top_labels,
        top_values=top_values,
        tong_hoa_don=tong_hoa_don,
        tong_doanh_thu=tong_doanh_thu,
        start_date=start_date,
        end_date=end_date
    )

if __name__ == "__main__":
    app.run(debug=True)