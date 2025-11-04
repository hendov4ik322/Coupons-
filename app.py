from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse
from datetime import datetime
from typing import Dict, Any
import sqlite3
import secrets
import string
import datetime as dt

app = FastAPI()

# ===========================
#  DATABASE & BUSINESS LOGIC
# ===========================

DB = 'referral.db'
ALPHABET = ''.join([c for c in string.ascii_uppercase + string.digits if c not in "IO01"])

def now():
    return dt.datetime.utcnow()

def gen_code(length=5):
    return ''.join(secrets.choice(ALPHABET) for _ in range(length))

def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id TEXT UNIQUE,
        tg_username TEXT,
        total_invites INTEGER DEFAULT 0,
        total_purchases INTEGER DEFAULT 0,
        created_at TEXT
    )""")
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS coupons(
        code TEXT PRIMARY KEY,
        coupon_type TEXT,
        discount_percent INTEGER,
        stars_count INTEGER,
        min_stars INTEGER DEFAULT 1,
        owner_tg_id TEXT,
        inviter_tg_id TEXT,
        invited_tg_id TEXT,
        status TEXT,
        created_at TEXT,
        expires_at TEXT,
        used_at TEXT
    )""")
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS referrals(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inviter_tg_id TEXT,
        invited_tg_id TEXT,
        inviter_coupon_code TEXT,
        invited_coupon_code TEXT,
        status TEXT,
        created_at TEXT,
        completed_at TEXT
    )""")
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS purchases(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        buyer_tg_id TEXT,
        stars_count INTEGER,
        coupon_code TEXT,
        discount_percent INTEGER,
        created_at TEXT
    )""")
    
    conn.commit()
    conn.close()

def create_user(tg_id, tg_username=None):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT tg_id FROM users WHERE tg_id = ?", (tg_id,))
    existing = cur.fetchone()
    if not existing:
        cur.execute("INSERT INTO users(tg_id, tg_username, created_at) VALUES(?,?,?)",
                    (tg_id, tg_username, now().isoformat()))
    elif tg_username:
        cur.execute("UPDATE users SET tg_username = ? WHERE tg_id = ?", (tg_username, tg_id))
    conn.commit()
    conn.close()
    return tg_id

def create_coupon(coupon_type, discount_percent, stars_count, owner_tg_id=None,
                  inviter_tg_id=None, invited_tg_id=None, min_stars=1, days_valid=30):
    code = gen_code()
    created = now().isoformat()
    expires = (now() + dt.timedelta(days=days_valid)).isoformat()
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO coupons(
            code, coupon_type, discount_percent, stars_count, min_stars,
            owner_tg_id, inviter_tg_id, invited_tg_id, status, created_at, expires_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (code, coupon_type, discount_percent, stars_count, min_stars,
          owner_tg_id, inviter_tg_id, invited_tg_id, 'active', created, expires))
    conn.commit()
    conn.close()
    return code

def start_invite(inviter_tg_id, invited_tg_id,
                 invited_discount_percent: int, inviter_reward_percent: int,
                 inviter_username=None, invited_username=None) -> Dict[str, str]:
    create_user(inviter_tg_id, inviter_username)
    create_user(invited_tg_id, invited_username)
    
    invited_coupon = create_coupon(
        'invited_discount', invited_discount_percent, 10,
        owner_tg_id=invited_tg_id,
        inviter_tg_id=inviter_tg_id,
        invited_tg_id=invited_tg_id,
        min_stars=10
    )
    
    inviter_coupon = create_coupon(
        'inviter_reward', inviter_reward_percent, 1,
        owner_tg_id=inviter_tg_id,
        inviter_tg_id=inviter_tg_id,
        invited_tg_id=invited_tg_id,
        min_stars=1
    )
    
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO referrals(
            inviter_tg_id, invited_tg_id, inviter_coupon_code,
            invited_coupon_code, status, created_at
        ) VALUES (?,?,?,?,?,?)
    """, (inviter_tg_id, invited_tg_id, inviter_coupon, invited_coupon, 'pending', now().isoformat()))
    
    cur.execute("UPDATE users SET total_invites = total_invites + 1 WHERE tg_id = ?", (inviter_tg_id,))
    conn.commit()
    conn.close()
    
    return {
        'inviter_coupon': inviter_coupon,
        'invited_coupon': invited_coupon
    }

def complete_purchase(buyer_tg_id: str, stars_count: int, coupon_code: str = None) -> Dict[str, Any]:
    create_user(buyer_tg_id)
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    used_discount = 0
    
    if coupon_code:
        cur.execute("""
            SELECT discount_percent, min_stars, status, owner_tg_id, expires_at
            FROM coupons WHERE code = ?
        """, (coupon_code,))
        coupon = cur.fetchone()
        if not coupon:
            conn.close()
            return {'ok': False, 'reason': 'coupon_not_found'}
        
        discount_percent, min_stars, status, owner_tg_id, expires_at = coupon
        expires_dt = dt.datetime.fromisoformat(expires_at)
        
        if status != 'active':
            conn.close()
            return {'ok': False, 'reason': 'coupon_not_active'}
        if now() > expires_dt:
            conn.close()
            return {'ok': False, 'reason': 'coupon_expired'}
        if owner_tg_id != buyer_tg_id:
            conn.close()
            return {'ok': False, 'reason': 'coupon_belongs_to_another_user'}
        
        used_discount = discount_percent
        cur.execute("UPDATE coupons SET status = 'used', used_at = ? WHERE code = ?",
                    (now().isoformat(), coupon_code))
        cur.execute("UPDATE referrals SET status = 'completed', completed_at = ? WHERE invited_coupon_code = ?",
                    (now().isoformat(), coupon_code))
    
    cur.execute("""
        INSERT INTO purchases(buyer_tg_id, stars_count, coupon_code, discount_percent, created_at)
        VALUES (?,?,?,?,?)
    """, (buyer_tg_id, stars_count, coupon_code, used_discount, now().isoformat()))
    
    cur.execute("UPDATE users SET total_purchases = total_purchases + 1 WHERE tg_id = ?", (buyer_tg_id,))
    conn.commit()
    conn.close()
    
    return {'ok': True, 'stars_count': stars_count, 'used_discount_percent': used_discount}

def list_coupons():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            c.code, c.coupon_type, c.discount_percent, c.stars_count, c.min_stars,
            c.owner_tg_id, u_owner.tg_username,
            c.inviter_tg_id, u_inviter.tg_username,
            c.invited_tg_id, u_invited.tg_username,
            c.status, c.created_at, c.expires_at, c.used_at
        FROM coupons c
        LEFT JOIN users u_owner ON c.owner_tg_id = u_owner.tg_id
        LEFT JOIN users u_inviter ON c.inviter_tg_id = u_inviter.tg_id
        LEFT JOIN users u_invited ON c.invited_tg_id = u_invited.tg_id
        ORDER BY c.created_at DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

def delete_coupon(code: str) -> Dict[str, Any]:
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("DELETE FROM coupons WHERE code = ?", (code,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return {'ok': deleted, 'message': 'Coupon deleted' if deleted else 'Coupon not found'}

# ===========================
#  FASTAPI APP
# ===========================

init_db()

def create_button_response(title: str, message: str, is_error: bool = False) -> str:
    color = "#ff4500" if is_error else "#45a295"
    return f"""
    <html>
    <head>
        <title>{title}</title>
        <style>
            body {{ font-family: 'Segoe UI', sans-serif; margin: 30px; background: linear-gradient(135deg, #1f2833 0%, #0b0c0f 100%); color: #f0f0f0; text-align: center; }}
            .container {{ background: #2a3440; padding: 40px; border-radius: 12px; margin: 50px auto; max-width: 600px; box-shadow: 0 4px 12px rgba(0,0,0,0.5); border-left: 5px solid {color};}}
            h2 {{ color: {color}; }}
            .back-button {{
                display: inline-block;
                padding: 12px 25px;
                margin-top: 20px;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                cursor: pointer;
                transition: transform 0.2s, box-shadow 0.2s;
                text-decoration: none;
                color: #1f2833;
                background: #66fcf1;
                box-shadow: 0 4px 6px rgba(102, 252, 241, 0.3);
            }}
            .back-button:hover {{
                transform: translateY(-2px);
                box-shadow: 0 6px 10px rgba(102, 252, 241, 0.5);
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>{title}</h2>
            {message}
            <a href='/' class='back-button'>⬅️ Вернуться к Панели</a>
        </div>
    </body>
    </html>
    """

@app.get("/", response_class=HTMLResponse)
def home():
    coupons = list_coupons()
    table_rows = ""
    for c in coupons:
        (code, c_type, discount, stars_count, min_stars,
         owner_id, owner_username,
         inviter_id, inviter_username,
         invited_id, invited_username,
         status, created, expires, used) = c
        
        created_fmt = datetime.fromisoformat(created).strftime("%Y-%m-%d %H:%M:%S") if created else "-"
        expires_fmt = datetime.fromisoformat(expires).strftime("%Y-%m-%d %H:%M:%S") if expires else "-"
        used_fmt = datetime.fromisoformat(used).strftime("%Y-%m-%d %H:%M:%S") if used else "-"
        
        def format_user(tg_id, username):
            if not tg_id:
                return "-"
            if username:
                return f"{tg_id} / @{username}"
            else:
                return f"{tg_id} / —"
        
        owner_display = format_user(owner_id, owner_username)
        inviter_display = format_user(inviter_id, inviter_username)
        invited_display = format_user(invited_id, invited_username)
        
        color = "#2a3440" if status == "active" else "#1f2833" if status == "used" else "#502828" if status == "expired" else "#2a3440"
        
        table_rows += f"""
        <tr style="background:{color}">
            <td>{code}</td>
            <td>{c_type}</td>
            <td>{discount}%</td>
            <td>{owner_display}</td>
            <td>{inviter_display}</td>
            <td>{invited_display}</td>
            <td>{status}</td>
            <td>{created_fmt}</td>
            <td>{expires_fmt}</td>
            <td>{used_fmt}</td>
            <td><button class="delete-btn" onclick="deleteCoupon('{code}')">🗑️ Delete</button></td>
        </tr>
        """

    html = f"""
    <html>
    <head>
        <title>Referral Coupons Dashboard</title>
        <style>
            body {{ 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                margin: 0; 
                padding: 30px; 
                background: linear-gradient(135deg, #1f2833 0%, #0b0c0f 100%); 
                color: #f0f0f0;
            }}
            h1 {{ 
                color: #66fcf1; 
                text-align: center; 
                margin-bottom: 40px; 
                text-shadow: 0 0 5px rgba(102, 252, 241, 0.5);
            }}
            
            .form-section {{ 
                background: #2a3440; 
                padding: 30px; 
                border-radius: 16px; 
                margin-bottom: 30px; 
                box-shadow: 0 4px 25px rgba(0,0,0,0.3); 
                border: 1px solid rgba(69, 162, 149, 0.2);
                transition: all 0.3s ease;
                position: relative;
                overflow: hidden;
            }}
            .form-section::before {{
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 3px;
                background: linear-gradient(90deg, #45a295, #66fcf1);
            }}
            .form-section:hover {{
                transform: translateY(-5px);
                box-shadow: 0 8px 35px rgba(0,0,0,0.4);
            }}
            .form-section h2 {{
                color: #66fcf1;
                border-bottom: 2px solid rgba(31, 40, 51, 0.5);
                padding-bottom: 15px;
                margin-top: 0;
                margin-bottom: 25px;
                font-size: 1.5em;
                letter-spacing: 1px;
            }}
            
            input[type=text], input[type=number] {{ 
                padding: 15px 20px; 
                margin: 8px 0; 
                width: 100%; 
                border-radius: 12px; 
                border: 2px solid #45a295; 
                background: rgba(31, 40, 51, 0.7);
                color: #f0f0f0; 
                box-sizing: border-box;
                transition: all 0.3s ease;
                font-size: 1em;
                letter-spacing: 0.5px;
                backdrop-filter: blur(5px);
            }}
            
            input[type=number]::-webkit-inner-spin-button,
            input[type=number]::-webkit-outer-spin-button {{
                -webkit-appearance: none;
                margin: 0;
            }}
            input[type=number] {{
                -moz-appearance: textfield;
            }}
            
            input[type=text]:hover, input[type=number]:hover {{
                border-color: #66fcf1;
                background: rgba(31, 40, 51, 0.8);
                transform: translateY(-1px);
                box-shadow: 0 5px 15px rgba(102, 252, 241, 0.1);
            }}
            
            input[type=text]:focus, input[type=number]:focus {{
                border-color: #66fcf1;
                box-shadow: 0 0 20px rgba(102, 252, 241, 0.2);
                outline: none;
                background: rgba(31, 40, 51, 0.9);
                transform: translateY(-2px);
            }}
            
            input::placeholder {{
                color: #7a8b9c;
            }}
            
            input:focus::placeholder {{
                opacity: 0.7;
                transform: translateX(5px);
            }}
            
            input[type=submit] {{ 
                background: linear-gradient(45deg, #45a295, #378579); 
                color: #fff; 
                border: none; 
                cursor: pointer; 
                font-weight: bold;
                letter-spacing: 1px;
                box-shadow: 0 4px 15px rgba(69, 162, 149, 0.3);
                padding: 15px 30px; 
                margin-top: 20px;
                border-radius: 12px; 
                width: 100%;
                transition: all 0.3s ease;
                text-transform: uppercase;
                font-size: 0.9em;
            }}
            input[type=submit]:hover {{ 
                background: linear-gradient(45deg, #378579, #2a6a61);
                box-shadow: 0 6px 20px rgba(69, 162, 149, 0.4);
                transform: translateY(-2px);
            }}
            input[type=submit]:active {{
                transform: translateY(1px);
                box-shadow: 0 2px 10px rgba(69, 162, 149, 0.2);
            }}
            
            table {{ 
                width: 100%; 
                border-collapse: collapse; 
                background: #2a3440; 
                border-radius: 12px; 
                overflow: hidden; 
                box-shadow: 0 4px 12px rgba(0,0,0,0.5);
                margin-top: 20px;
            }}
            th, td {{ 
                padding: 15px 10px; 
                border-bottom: 1px solid #1f2833; 
                text-align: left;
                font-size: 0.9em;
            }}
            th {{ 
                background: #1f2833; 
                color: #66fcf1; 
                font-weight: 600; 
                position: sticky; 
                top: 0; 
                letter-spacing: 0.1px;
            }}
            tr:hover {{ 
                background: #3a4759 !important; 
                transition: background-color 0.2s;
            }}
            
            .delete-btn {{ 
                background: #ff4500; 
                color: white; 
                border: none; 
                padding: 6px 12px; 
                border-radius: 6px; 
                cursor: pointer; 
                font-size: 0.8em; 
                transition: background-color 0.3s;
            }}
            .delete-btn:hover {{ 
                background: #cc3700; 
            }}
        </style>
        <script>
            async function deleteCoupon(code) {{
                if (confirm('Are you sure you want to delete coupon ' + code + '?')) {{
                    const response = await fetch(`/coupon/${{code}}`, {{ method:'DELETE' }});
                    const result = await response.json();
                    if(result.ok) window.location.reload();
                    else alert('Failed to delete coupon: ' + result.message);
                }}
            }}
        </script>
    </head>
    <body>
        <h1>⭐ Referral Coupons Dashboard ⭐</h1>
        
        <div class="form-section" id="invite-section">
            <h2>🤝 Создать Реферал</h2>
            <form action="/invite" method="post">
                <input name="inviter_id" placeholder="ID Пригласившего (required)" required>
                <input name="inviter_username" placeholder="Username Пригласившего (optional)">
                <input name="invited_id" placeholder="ID Приглашенного (required)" required>
                <input name="invited_username" placeholder="Username Приглашенного (optional)">
                <input name="invited_discount" type="number" placeholder="Скидка для Приглашенного (%)" required min="1" max="99">
                <input name="inviter_reward" type="number" placeholder="Награда Пригласившему (%)" required min="1" max="99">
                <input type="submit" value="Создать Реферальную Пару">
            </form>
        </div>

        <div class="form-section" id="purchase-section">
            <h2>🛒 Совершить Покупку</h2>
            <form action="/purchase" method="post">
                <input name="buyer_id" placeholder="ID Покупателя (required)" required>
                <input name="coupon" placeholder="Код Купона (optional)">
                <input type="submit" value="Применить Купон и Купить">
            </form>
        </div>

        <h2>📜 Все Купоны</h2>
        <table>
            <tr>
                <th>Код</th>
                <th>Тип</th>
                <th>Скидка</th>
                <th>Владелец (ID / @Username)</th>
                <th>Пригласивший (ID / @Username)</th>
                <th>Приглашенный (ID / @Username)</th>
                <th>Статус</th>
                <th>Создан</th>
                <th>Истекает</th>
                <th>Использован</th>
                <th>Действия</th>
            </tr>
            {table_rows}
        </table>
    </body>
    </html>
    """
    return HTMLResponse(html)

@app.post("/invite", response_class=HTMLResponse)
def invite_form(
    inviter_id: str = Form(...),
    invited_id: str = Form(...),
    invited_discount: int = Form(...),
    inviter_reward: int = Form(...),
    inviter_username: str = Form(None),
    invited_username: str = Form(None)
):
    try:
        if inviter_id == invited_id:
            raise ValueError("Inviter and Invited IDs cannot be the same.")
        result = start_invite(
            inviter_id, invited_id,
            invited_discount, inviter_reward,
            inviter_username, invited_username
        )
        message = f"""
            <p>Купон для Пригласившего ({inviter_reward}%): <b>{result['inviter_coupon']}</b></p>
            <p>Купон для Приглашенного ({invited_discount}%): <b>{result['invited_coupon']}</b></p>
        """
        return create_button_response("✅ Успех!", message, is_error=False)
    except Exception as e:
        message = f"<p>Не удалось создать приглашение: <b>{e}</b></p>"
        return create_button_response("❌ Ошибка!", message, is_error=True)

@app.post("/purchase", response_class=HTMLResponse)
def purchase_form(buyer_id: str = Form(...), coupon: str = Form(None)):
    stars_count = 1
    try:
        result = complete_purchase(buyer_id, stars_count, coupon)
        if result['ok']:
            message = f"""
                <p>Использована Скидка: <b>{result['used_discount_percent']}%</b></p>
            """
            return create_button_response("🎉 Покупка Завершена!", message, is_error=False)
        else:
            message = f"<p>Причина: <b>{result['reason']}</b></p>"
            return create_button_response("❌ Покупка Не Удалась!", message, is_error=True)
    except Exception as e:
        message = f"<p>Ошибка: <b>{e}</b></p>"
        return create_button_response("❌ Непредвиденная Ошибка!", message, is_error=True)

@app.delete("/coupon/{code}")
def delete_coupon_endpoint(code: str) -> Dict[str, Any]:
    return delete_coupon(code)
