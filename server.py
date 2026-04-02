from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import sqlite3, random, numpy as np, os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder=BASE_DIR)
CORS(app)
DB = os.path.join(BASE_DIR, 'credit.db')

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS borrowers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, age INTEGER, annual_income REAL,
        employment_length INTEGER, loan_amount REAL,
        num_open_lines INTEGER,
        num_delinquencies INTEGER, credit_utilization REAL,
        credit_history_years INTEGER, num_inquiries INTEGER,
        dti REAL, credit_score INTEGER, risk_category TEXT,
        default_prob REAL, default_status INTEGER,
        status_override TEXT, override_reason TEXT, created_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        borrower_id INTEGER, borrower_name TEXT,
        field_changed TEXT, old_value TEXT, new_value TEXT,
        reason TEXT, changed_at TEXT
    )''')
    conn.commit()
    c.execute('SELECT COUNT(*) FROM borrowers')
    if c.fetchone()[0] == 0:
        print("Database empty — seeding 500 borrowers...")
        seed_data(conn)
        print("Done.")
    conn.close()

def seed_data(conn):
    random.seed(42)
    np.random.seed(42)
    first_names = ['Aarav','Priya','Rohan','Sneha','Vikram','Ananya','Kiran','Pooja',
                   'Arjun','Meera','Rahul','Nisha','Suresh','Divya','Amit','Kavya',
                   'Rajesh','Sanya','Deepak','Riya','Siddharth','Anjali','Manish',
                   'Swati','Aakash','Neha','Gaurav','Isha','Varun','Shreya']
    last_names  = ['Sharma','Patel','Singh','Kumar','Gupta','Joshi','Mehta','Nair',
                   'Reddy','Iyer','Verma','Rao','Chopra','Desai','Malhotra']
    rows = []
    for _ in range(500):
        age    = random.randint(22, 68)
        income = int(np.clip(np.random.lognormal(10.8, 0.5), 20000, 300000))
        emp    = random.choice([0, 1, 2, 3, 5, 7, 10, 15, 20])
        loan   = random.randint(1000, 40000)
        lines  = random.randint(1, 30)
        delinq = random.choice([0, 1, 2, 3, 4, 5])
        util   = round(random.betavariate(2, 5), 3)
        hist   = random.randint(1, 30)
        inq    = random.choice([0, 1, 2, 3, 4, 5, 6])
        dti    = round((loan / income) * 100, 2)
        name   = f"{random.choice(first_names)} {random.choice(last_names)}"
        risk = (0.55*(dti/50) + 0.40*util + 0.35*(delinq/5)
                - 0.20*(income/150000) - 0.15*(hist/30) - 0.10*(emp/20)
                + random.gauss(0, 0.12))
        prob     = round(min(0.99, max(0.01, 1/(1+np.exp(-(risk-0.55)*5)))), 3)
        default  = 1 if prob > 0.50 else 0
        cs       = int(np.clip(850 - prob*520, 300, 850))
        category = ('Excellent' if cs >= 750 else 'Good' if cs >= 700
                    else 'Fair' if cs >= 650 else 'Poor' if cs >= 600 else 'Very Poor')
        rows.append((name, age, income, emp, loan, lines, delinq, util, hist,
                     inq, dti, cs, category, prob, default,
                     None, None, datetime.now().isoformat()))
    conn.executemany('''INSERT INTO borrowers
        (name,age,annual_income,employment_length,loan_amount,num_open_lines,
         num_delinquencies,credit_utilization,credit_history_years,
         num_inquiries,dti,credit_score,risk_category,default_prob,
         default_status,status_override,override_reason,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', rows)
    conn.commit()


@app.route('/api/borrowers', methods=['GET'])
def get_borrowers():
    page     = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    search   = request.args.get('search', '').strip()
    filter_  = request.args.get('filter', 'all')
    sort_by  = request.args.get('sort', 'id')
    sort_dir = request.args.get('dir', 'asc')
    allowed  = {'id','name','age','annual_income','loan_amount','credit_score',
                'risk_category','num_delinquencies','credit_utilization',
                'default_prob','default_status'}
    if sort_by not in allowed:
        sort_by = 'id'
    where, params = [], []
    if search:
        where.append('name LIKE ?')
        params.append(f'%{search}%')
    if filter_ == 'default':
        where.append("default_status=1 AND COALESCE(status_override,'')!='safe'")
    elif filter_ == 'safe':
        where.append("(status_override='safe' OR default_status=0)")
    elif filter_ == 'edited':
        where.append("status_override IS NOT NULL")
    where_sql = ('WHERE ' + ' AND '.join(where)) if where else ''
    dir_sql   = 'DESC' if sort_dir == 'desc' else 'ASC'
    conn  = get_db()
    total = conn.execute(f'SELECT COUNT(*) FROM borrowers {where_sql}', params).fetchone()[0]
    rows  = conn.execute(
        f'SELECT * FROM borrowers {where_sql} ORDER BY {sort_by} {dir_sql} LIMIT ? OFFSET ?',
        params + [per_page, (page-1)*per_page]
    ).fetchall()
    conn.close()
    return jsonify({'total':total,'page':page,'per_page':per_page,
                    'pages':(total+per_page-1)//per_page,
                    'borrowers':[dict(r) for r in rows]})


@app.route('/api/borrowers', methods=['POST'])
def add_borrower():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    name   = str(data.get('name', 'Unknown')).strip() or 'Unknown'
    age    = max(18, min(100, int(data.get('age', 30))))
    income = float(data.get('annual_income', 50000))
    emp    = max(0, int(data.get('employment_length', 5)))
    loan   = float(data.get('loan_amount', 10000))
    lines  = max(0, int(data.get('num_open_lines', 5)))
    delinq = max(0, int(data.get('num_delinquencies', 0)))
    util   = float(data.get('credit_utilization', 0.3))
    hist   = max(0, int(data.get('credit_history_years', 5)))
    inq    = max(0, int(data.get('num_inquiries', 1)))

    if income <= 0:
        return jsonify({'error': 'annual_income must be greater than 0'}), 400

    util = max(0.0, min(1.0, util))
    dti  = round((loan / income) * 100, 2)
    risk = (0.55*(dti/50) + 0.40*util + 0.35*(delinq/5)
            - 0.20*(income/150000) - 0.15*(hist/30) - 0.10*(emp/20))
    prob = round(min(0.99, max(0.01, 1/(1+np.exp(-(risk-0.55)*5)))), 3)
    cs   = int(np.clip(850 - prob*520, 300, 850))
    cat  = ('Excellent' if cs >= 750 else 'Good' if cs >= 700
            else 'Fair' if cs >= 650 else 'Poor' if cs >= 600 else 'Very Poor')
    default = 1 if prob > 0.5 else 0

    conn = get_db()
    cur = conn.execute('''INSERT INTO borrowers
        (name,age,annual_income,employment_length,loan_amount,num_open_lines,
         num_delinquencies,credit_utilization,credit_history_years,
         num_inquiries,dti,credit_score,risk_category,default_prob,
         default_status,status_override,override_reason,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (name,age,income,emp,loan,lines,delinq,util,hist,
         inq,dti,cs,cat,prob,default,None,None,datetime.now().isoformat()))
    conn.commit()
    new_id = cur.lastrowid
    row = conn.execute('SELECT * FROM borrowers WHERE id=?', (new_id,)).fetchone()
    conn.close()
    return jsonify({'success': True, 'borrower': dict(row)}), 201


@app.route('/api/borrowers/<int:bid>', methods=['GET'])
def get_one_borrower(bid):
    conn = get_db()
    row  = conn.execute('SELECT * FROM borrowers WHERE id=?', (bid,)).fetchone()
    logs = conn.execute(
        'SELECT * FROM audit_log WHERE borrower_id=? ORDER BY changed_at DESC', (bid,)
    ).fetchall()
    conn.close()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'borrower': dict(row), 'history': [dict(l) for l in logs]})


@app.route('/api/borrowers/<int:bid>', methods=['PUT'])
def update_borrower(bid):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body required'}), 400
    conn = get_db()
    old  = conn.execute('SELECT * FROM borrowers WHERE id=?', (bid,)).fetchone()
    if not old:
        conn.close()
        return jsonify({'error': 'Not found'}), 404

    income   = float(data.get('annual_income',       old['annual_income']))
    emp      = int(data.get('employment_length',      old['employment_length']))
    loan     = float(data.get('loan_amount',          old['loan_amount']))
    util     = float(data.get('credit_utilization',   old['credit_utilization']))
    delinq   = int(data.get('num_delinquencies',      old['num_delinquencies']))
    hist     = int(data.get('credit_history_years',   old['credit_history_years']))
    inq      = int(data.get('num_inquiries',          old['num_inquiries']))
    override = data.get('status_override',            old['status_override'])
    reason   = data.get('override_reason',            old['override_reason'])

    if income <= 0:
        conn.close()
        return jsonify({'error': 'annual_income must be greater than 0'}), 400

    util = max(0.0, min(1.0, util))

    dti  = round((loan / income) * 100, 2)
    risk = (0.55*(dti/50) + 0.40*util + 0.35*(delinq/5)
            - 0.20*(income/150000) - 0.15*(hist/30) - 0.10*(emp/20))
    prob = round(min(0.99, max(0.01, 1/(1+np.exp(-(risk-0.55)*5)))), 3)
    cs   = int(np.clip(850 - prob*520, 300, 850))
    cat  = ('Excellent' if cs >= 750 else 'Good' if cs >= 700
            else 'Fair' if cs >= 650 else 'Poor' if cs >= 600 else 'Very Poor')
    default = 1 if prob > 0.5 else 0

    conn.execute('''UPDATE borrowers SET
        annual_income=?,employment_length=?,loan_amount=?,
        credit_utilization=?,num_delinquencies=?,credit_history_years=?,
        num_inquiries=?,dti=?,credit_score=?,risk_category=?,
        default_prob=?,default_status=?,status_override=?,override_reason=?
        WHERE id=?''',
        (income,emp,loan,util,delinq,hist,inq,dti,cs,cat,prob,default,override,reason,bid))

    tracked = ['annual_income','employment_length','loan_amount',
               'credit_utilization','num_delinquencies','status_override']
    for field in tracked:
        old_val = old[field]
        new_val = data.get(field, old_val)
        if str(old_val) != str(new_val):
            conn.execute('''INSERT INTO audit_log
                (borrower_id,borrower_name,field_changed,old_value,new_value,reason,changed_at)
                VALUES (?,?,?,?,?,?,?)''',
                (bid,old['name'],field,str(old_val),str(new_val),
                 reason or '',datetime.now().isoformat()))

    conn.commit()
    updated = conn.execute('SELECT * FROM borrowers WHERE id=?', (bid,)).fetchone()
    conn.close()
    return jsonify({'success':True,'borrower':dict(updated),'new_score':cs,'new_category':cat})


@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn     = get_db()
    total    = conn.execute('SELECT COUNT(*) FROM borrowers').fetchone()[0]
    defaults = conn.execute(
        "SELECT COUNT(*) FROM borrowers WHERE default_status=1 AND COALESCE(status_override,'')!='safe'"
    ).fetchone()[0]
    edits    = conn.execute("SELECT COUNT(*) FROM borrowers WHERE status_override IS NOT NULL").fetchone()[0]
    avg_cs   = conn.execute('SELECT AVG(credit_score) FROM borrowers').fetchone()[0]
    avg_loan = conn.execute('SELECT AVG(loan_amount) FROM borrowers').fetchone()[0]
    avg_inc  = conn.execute('SELECT AVG(annual_income) FROM borrowers').fetchone()[0]
    risk_dist = conn.execute(
        'SELECT risk_category, COUNT(*) as cnt FROM borrowers GROUP BY risk_category'
    ).fetchall()
    income_def = conn.execute('''
        SELECT
            CASE WHEN annual_income < 30000  THEN "<30K"
                 WHEN annual_income < 60000  THEN "30-60K"
                 WHEN annual_income < 100000 THEN "60-100K"
                 WHEN annual_income < 150000 THEN "100-150K"
                 ELSE "150K+" END AS bracket,
            AVG(CASE WHEN default_status=1 AND COALESCE(status_override,"")!="safe"
                     THEN 1.0 ELSE 0.0 END) as rate
        FROM borrowers GROUP BY bracket
    ''').fetchall()
    recent = conn.execute('SELECT * FROM audit_log ORDER BY changed_at DESC LIMIT 10').fetchall()
    conn.close()
    return jsonify({
        'total'              : total,
        'default_count'      : defaults,
        'default_rate'       : round(defaults/total*100, 1) if total else 0,
        'edits'              : edits,
        'avg_credit_score'   : round(avg_cs)   if avg_cs   else 0,
        'avg_loan_amount'    : round(avg_loan) if avg_loan else 0,
        'avg_income'         : round(avg_inc)  if avg_inc  else 0,
        'risk_distribution'  : {r['risk_category']: r['cnt'] for r in risk_dist},
        'income_default_rate': {r['bracket']: round(r['rate'],3) for r in income_def},
        'recent_changes'     : [dict(r) for r in recent]
    })


@app.route('/api/audit', methods=['GET'])
def get_audit():
    conn = get_db()
    logs = conn.execute('SELECT * FROM audit_log ORDER BY changed_at DESC LIMIT 100').fetchall()
    conn.close()
    return jsonify([dict(l) for l in logs])


@app.route('/')
def serve_index():
    return send_from_directory(BASE_DIR, 'index.html')


if __name__ == '__main__':
    print("Starting CreditLens server...")
    init_db()
    print("Open your browser:  http://localhost:5000")
    app.run(debug=True, port=5000)
