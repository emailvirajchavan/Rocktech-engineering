from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import psycopg2
from psycopg2 import sql
import os
import urllib.parse as urlparse

app = Flask(__name__)
app.secret_key = 'your_secret_key'  

# PostgreSQL DB configuration


def get_db_connection():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise Exception("DATABASE_URL not set")

    result = urlparse.urlparse(url)

    return psycopg2.connect(
        database=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port
    )

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user:
            session['user'] = user[1]
            return redirect(url_for('deposit_part'))
        else:
            flash("Invalid username or password", "danger")
            return redirect(url_for('login'))

    return render_template('index.html') 

# @app.route('/deposit_part')
# def deposit_part():
#     if 'user' not in session:
#         return redirect(url_for('login'))
#     return render_template('deposit_part.html', user=session['user'])

# Display Deposit Form
@app.route('/deposit_part')
def deposit_part():
    if 'user' not in session:
        return redirect('/login')
    
    conn =  get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT type_id, type_name FROM vehicle_type")
    vehicle_types = cur.fetchall()
    cur.close()
    conn.close()
    
    return render_template(
        'deposit_part.html',
        vehicle_types=[{'id': vt[0], 'name': vt[1]} for vt in vehicle_types],
        user=session['user']
    )

# Get Vehicles by Vehicle Type ID
@app.route('/get_vehicles/<int:type_id>')
def get_vehicles(type_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT vehicle_id, vehicle_name FROM vehicles WHERE type_id = %s", (type_id,))
    vehicles = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{'id': v[0], 'name': v[1]} for v in vehicles])

# Get Parts by Vehicle ID
@app.route('/get_parts/<int:vehicle_id>')
def get_parts(vehicle_id):
    conn =  get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT part_id, part_name FROM parts WHERE vehicle_id = %s", (vehicle_id,))
    parts = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{'id': p[0], 'name': p[1]} for p in parts])

# Handle Deposit Form Submission
@app.route('/submit-deposit', methods=['POST'])
def submit_deposit():
    vehicle_type_id = request.form['vehicle_type_id']
    vehicle_id = request.form['vehicle_id']
    part_id = request.form['part_id']
    qty = request.form['deposite_qty']

    conn = get_db_connection()
    cur = conn.cursor()

    # Insert and RETURN the new deposit_id
    cur.execute("""
        INSERT INTO deposit (vehicle_type_id, vehicle_id, part_id, deposit_qty, deposit_status)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING deposit_id
    """, (vehicle_type_id, vehicle_id, part_id, qty, 1))

    deposit_id_row = cur.fetchone()
    deposit_id = deposit_id_row[0] if deposit_id_row else None

    conn.commit()
    cur.close()
    conn.close()

    if deposit_id:
        return f"""
        <script>
            alert('Deposit submitted successfully!');
            window.location.href = '/issue_form/{deposit_id}';
        </script>
        """
    else:
        return """
        <script>
            alert('Failed to submit deposit!');
            window.location.href = '/deposit_part';
        </script>
        """



@app.route('/issue_form')
@app.route('/issue_form/<int:deposit_id>')
def issue_form_with_id(deposit_id):
    if 'user' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cur = conn.cursor()

    # Fetch only the specific deposit that was just submitted
    cur.execute("""
        SELECT d.deposit_id, vt.type_name, v.vehicle_name, p.part_name
        FROM deposit d
        JOIN vehicle_type vt ON d.vehicle_type_id = vt.type_id
        JOIN vehicles v ON d.vehicle_id = v.vehicle_id
        JOIN parts p ON d.part_id = p.part_id
        WHERE d.deposit_id = %s AND d.deposit_status = 1
    """, (deposit_id,))
    row = cur.fetchone()

    cur.close()
    conn.close()

    # Prepare dropdown data (only one entry)
    deposit_data = {}
    if row:
        deposit_data[row[0]] = {
            "vehicleType": row[1],
            "vehicleName": row[2],
            "partName": row[3]
        }

    return render_template('issue_part.html',
                           deposit_ids=deposit_data.keys(),
                           deposit_data=deposit_data,
                           selected_id=deposit_id)

# Handle Issue Form Submission
@app.route('/submit-issue', methods=['POST'])
def submit_issue():
    deposit_id = request.form['deposit_id']
    issue_qty = int(request.form['issue_qty'])

    conn = get_db_connection()
    cur = conn.cursor()

    # Step 1: Get part_id from deposit
    cur.execute("SELECT part_id FROM deposit WHERE deposit_id = %s", (deposit_id,))
    result = cur.fetchone()

    if not result:
        cur.close()
        conn.close()
        return """
        <script>
            alert('Invalid deposit selected.');
            window.location.href = '/issue_form';
        </script>
        """

    part_id = result[0]

    # Step 2: Get current quantity from parts table
    cur.execute("SELECT quantity FROM parts WHERE part_id = %s", (part_id,))
    part_data = cur.fetchone()

    if not part_data or part_data[0] < issue_qty:
        cur.close()
        conn.close()
        return f"""
        <script>
            alert('Not enough quantity in stock to issue!');
            window.location.href = '/issue_form/{deposit_id}';
        </script>
        """

    # Step 3: Insert into issue table
    cur.execute("""
        INSERT INTO issue (deposit_id, issue_qty, issue_status)
        VALUES (%s, %s, %s)
    """, (deposit_id, issue_qty, 1))

    # Step 4: Update parts table quantity
    cur.execute("""
        UPDATE parts
        SET quantity = quantity - %s
        WHERE part_id = %s
    """, (issue_qty, part_id))

    conn.commit()
    cur.close()
    conn.close()
    
    return """ <script> alert('Issue submitted and part quantity updated!'); window.location.href = '/deposit_part';</script>"""


@app.route('/inventory')
def inventory():
    if 'user' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    # Join to get vehicle name and type for each part
    cur.execute("""
        SELECT p.part_id, p.part_name, p.quantity,
               v.vehicle_name, vt.type_name
        FROM parts p
        JOIN vehicles v ON p.vehicle_id = v.vehicle_id
        JOIN vehicle_type vt ON v.type_id = vt.type_id
        ORDER BY vt.type_name, v.vehicle_name, p.part_name
    """)
    
    parts = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('inventory.html', parts=parts, user=session['user'])

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=False)
