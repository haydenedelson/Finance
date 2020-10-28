import os

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd
from datetime import datetime

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():

    # Get stock symbols & shares from database
    # Store symbol, company name, number of shares, stock price, total value, and cash in holdings list
    holdings = db.execute("SELECT stock_symbol AS symbol, SUM(num_shares) AS quantity FROM transactions JOIN u_t_map ON id = transaction_id WHERE user_id = :uid GROUP BY stock_symbol HAVING quantity > 0 ORDER BY stock_symbol", uid=session["user_id"])

    # To calculate total_portfolio_value
    total_portfolio_value = 0

    for holding in holdings:

        # Convert quantity to int
        holding["quantity"] = int(holding["quantity"])

        # Get company name and current stock price
        stock = lookup(holding["symbol"])
        holding["name"] = stock["name"]
        holding["price"] = usd(stock["price"])

        # Calculate total holding value
        holding["total_value"] = usd(holding["quantity"] * stock["price"])

        # Add total holding value to total portfolio value
        total_portfolio_value += holding["quantity"] * stock["price"]

    # Get user's cash, append to holdings list
    user = db.execute("SELECT * FROM users WHERE id = :uid", uid=session["user_id"])
    holdings.append({
        "symbol": "Cash",
        "name": "",
        "price": "",
        "quantity": "",
        "total_value": usd(float(user[0]["cash"]))
    })

    # Add cash to total portfolio value
    total_portfolio_value += float(user[0]["cash"])

    holdings.append({
        "symbol": "total_portfolio_value",
        "name": "",
        "price": "",
        "quantity": "",
        "total_value": usd(total_portfolio_value)
    })

    return render_template("index.html", holdings=holdings)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    if request.method == "POST":

        # Ensure ticker field not blank
        if not request.form.get("ticker"):
            return apology("must input ticker", 400)

        # Ensure quantity field not blank
        elif not request.form.get("quantity"):
            return apology("must input quantity", 400)

        # Ensure quantity > 0
        elif int(request.form.get("quantity")) < 1:
            return apology("quantity must be 1 or more", 400)

        # Lookup stock ticker
        stock = lookup(request.form.get("ticker"))

        # If found, attempt transaction
        if not stock:
            return apology("ticker not found", 404)
        else:
            # Calculate total transaction cost
            quantity = int(request.form.get("quantity"))
            total_cost = quantity * stock["price"]

            # Check user cash balance
            user = db.execute("SELECT * FROM users WHERE id = :uid", uid=session["user_id"])
            cash = float(user[0]["cash"])

            # If sufficient cash -> update cash in users, record transaction in transactions & u_t_map
            if cash < total_cost:
                return apology("not enough cash", 403)
            else:
                transaction_time = datetime.now().strftime("%m/%d/%Y %I:%M:%S %p")
                db.execute("INSERT INTO transactions(stock_symbol, stock_price, num_shares, time) VALUES(:symbol, :price, :quantity, :time)", symbol=stock["symbol"], price=stock["price"], quantity=quantity, time=transaction_time)
                db.execute("INSERT INTO u_t_map VALUES(:uid, (SELECT MAX(id) FROM transactions))", uid=session["user_id"])
                db.execute("UPDATE users SET cash = :new_cash WHERE id = :uid", new_cash=(cash - total_cost), uid=session["user_id"])
                return redirect("/")

    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    transactions = db.execute("SELECT stock_symbol AS symbol, stock_price AS price, num_shares AS quantity, time FROM transactions JOIN u_t_map ON id = transaction_id WHERE user_id = :uid ORDER BY time DESC", uid=session["user_id"])
    for transaction in transactions:
        transaction["price"] = usd(float(transaction["price"]))
    return render_template("history.html", transactions=transactions)

@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    if request.method == "POST":

        # Ensure text field is not blank
        if not request.form.get("ticker"):
            return apology("must provide ticker", 400)

        # Lookup stock ticker
        stock_dict = lookup(request.form.get("ticker"))

        # If found, render quoted.html
        if not stock_dict:
            return apology("ticker not found", 404)
        else:
            stock = [stock_dict["symbol"], stock_dict["name"], usd(stock_dict["price"])]
            return render_template("quoted.html", stock=stock)

    else:
        return render_template("quote.html")

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure username is not taken
        users = db.execute("SELECT * FROM users WHERE username = :username", username=request.form.get("username"))
        if len(users) != 0:
            return apology("username taken", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Ensure passwords match
        elif not request.form.get("password") == request.form.get("confirmation"):
            return apology("passwords must match", 403)

        # All checks passed -> register user
        else:
            hash = generate_password_hash(request.form.get("password"))
            db.execute("INSERT INTO users (username, hash) VALUES (:username, :hash)", username=request.form.get("username"), hash=hash)
            return redirect("/login")

    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    if request.method == "POST":

        # Ensure ticker field not blank
        if not request.form.get("ticker"):
            return apology("must input ticker", 400)

        # Ensure quantity field not blank
        elif not request.form.get("quantity"):
            return apology("must input quantity", 400)

        #Ensure quantity > 0
        elif int(request.form.get("quantity")) < 1:
            return apology("quantity must be 1 or more", 400)

        # Ensure user owns sufficient quantity of stock
        user_stocks = db.execute("SELECT stock_symbol AS symbol, SUM(num_shares) AS quantity FROM transactions JOIN u_t_map ON id = transaction_id WHERE user_id = :uid GROUP BY stock_symbol HAVING quantity > 0", uid=session["user_id"])
        in_portfolio = False
        for stock in user_stocks:
            if stock["symbol"].upper() == request.form.get("ticker").upper():
                in_portfolio = True
            if int(stock["quantity"]) < int(request.form.get("quantity")):
                return apology("insufficient quantity", 400)

        # If user does not own stock, return apology
        if in_portfolio == False:
            return apology("stock not in portfolio", 400)

        # Lookup stock ticker
        stock = lookup(request.form.get("ticker"))

        # If found, attempt transaction
        if not stock:
            return apology("ticker not found", 404)
        else:
            # Calculate transaction value
            quantity = int(request.form.get("quantity"))
            total_value = quantity * stock["price"]

            transaction_time = datetime.now().strftime("%m/%d/%Y %I:%M:%S %p")
            db.execute("INSERT INTO transactions(stock_symbol, stock_price, num_shares, time) VALUES(:symbol, :price, :quantity, :time)", symbol=stock["symbol"], price=stock["price"], quantity=-quantity, time=transaction_time)
            db.execute("INSERT INTO u_t_map VALUES(:uid, (SELECT MAX(id) FROM transactions))", uid=session["user_id"])

            # Update user cash
            user = db.execute("SELECT * FROM users WHERE id = :uid", uid=session["user_id"])
            cash = float(user[0]["cash"])
            db.execute("UPDATE users SET cash = :new_cash WHERE id = :uid", new_cash=(cash + total_value), uid=session["user_id"])
            return redirect("/")
    else:
        return render_template("sell.html")


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
