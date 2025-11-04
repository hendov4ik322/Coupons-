from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse
from referral_system import init_db, start_invite, complete_purchase, list_coupons, delete_coupon
from datetime import datetime
from typing import Dict, Any

app = FastAPI()
init_db()

# --- Вспомогательные функции для HTML-ответа ---

def create_button_response(title: str, message: str, is_error: bool = False) -> str:
    """Генерирует HTML-ответ с сообщением и кнопкой 'Назад'."""
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

# --- Главная страница ---
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
        
        # Форматируем отображаемые имена
        owner_display = owner_username or owner_id or '-'
        inviter_display = inviter_username or inviter_id or '-'
        invited_display = invited_username or invited_id or '-'
        
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
            /* Сброс и Базовые Стили */
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
            
            /* Секции с формами */
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
            /* Поля ввода */
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
                transform: translateY(0);
            }}
            
            /* Убираем стрелки с number input */
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
                transition: all 0.3s ease;
            }}
            
            input:focus::placeholder {{
                opacity: 0.7;
                transform: translateX(5px);
            }}
            /* Кнопка отправки */
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
            /* Таблица (стили не менялись) */
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
            /* Кнопка удаления */
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
                <th>Код</th><th>Тип</th><th>Скидка</th><th>Владелец</th>
                <th>Пригласивший</th><th>Приглашенный</th><th>Статус</th>
                <th>Создан</th><th>Истекает</th><th>Использован</th><th>Действия</th>
            </tr>
            {table_rows}
        </table>
    </body>
    </html>
    """
    return HTMLResponse(html)

@app.post("/invite", response_class=HTMLResponse)
def invite_form(inviter_id: str = Form(...), invited_id: str = Form(...),
                invited_discount: int = Form(...), inviter_reward: int = Form(...),
                inviter_username: str = Form(None), invited_username: str = Form(None)):
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
