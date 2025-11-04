import sqlite3
import secrets
import string
import datetime
import time
from typing import Optional, Dict, Any

__all__ = ['init_db', 'start_invite', 'complete_purchase', 'list_coupons', 'delete_coupon']

DB = 'referral.db'

# --- utils ---
ALPHABET = ''.join([c for c in string.ascii_uppercase + string.digits if c not in "IO01"])

def now():
    return datetime.datetime.utcnow()

def gen_code(length=5):
    return ''.join(secrets.choice(ALPHABET) for _ in range(length))

# --- DB init (ИСПРАВЛЕНО: Одно закрытие соединения) ---
def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    
    # Таблица пользователей
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id TEXT UNIQUE,
        tg_username TEXT,
        total_invites INTEGER DEFAULT 0,
        total_purchases INTEGER DEFAULT 0,
        created_at TEXT
    )""")
    
    # Таблица купонов
    cur.execute("""
    CREATE TABLE IF NOT EXISTS coupons(
        code TEXT PRIMARY KEY,
        coupon_type TEXT,  -- 'invited_discount' или 'inviter_reward'
        discount_percent INTEGER,  -- процент скидки
        stars_count INTEGER,  -- количество звезд, на которое действует купон (для информации)
        min_stars INTEGER DEFAULT 1,  -- минимальное количество звезд для применения купона
        owner_tg_id TEXT,  -- владелец купона (tg_id)
        inviter_tg_id TEXT,  -- кто пригласил
        invited_tg_id TEXT,  -- кого пригласили
        status TEXT,  -- 'active', 'used', 'expired'
        created_at TEXT,
        expires_at TEXT,
        used_at TEXT
    )""")
    
    # Таблица рефералов
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
    
    # Таблица покупок (ПРОВЕРЕНО: содержит discount_percent)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS purchases(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        buyer_tg_id TEXT,
        stars_count INTEGER,  -- количество купленных звезд
        coupon_code TEXT,  -- использованный купон
        discount_percent INTEGER, -- процент использованной скидки
        created_at TEXT
    )""")
    
    conn.commit()
    conn.close()

# --- user operations ---
def create_user(tg_id, tg_username=None):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    
    # Проверяем существует ли пользователь
    cur.execute("SELECT tg_id FROM users WHERE tg_id = ?", (tg_id,))
    existing_user = cur.fetchone()
    
    if not existing_user:
        # Создаем нового пользователя
        created = now().isoformat()
        cur.execute("INSERT INTO users(tg_id, tg_username, created_at) VALUES(?,?,?)", 
                    (tg_id, tg_username, created))
    elif tg_username:
        # Обновляем username если он предоставлен
        cur.execute("UPDATE users SET tg_username = ? WHERE tg_id = ?", 
                    (tg_username, tg_id))
    
    conn.commit()
    conn.close()
    return tg_id


# --- coupon operations ---
def create_coupon(coupon_type, discount_percent, stars_count, owner_tg_id=None, 
                  inviter_tg_id=None, invited_tg_id=None, min_stars=1, days_valid=30):
    code = gen_code()
    created = now().isoformat()
    expires = (now() + datetime.timedelta(days=days_valid)).isoformat()
    
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


# --- invite and purchase flow ---
def start_invite(inviter_tg_id, invited_tg_id, 
                 invited_discount_percent: int, inviter_reward_percent: int,
                 inviter_username=None, invited_username=None) -> Dict[str, str]:
    
    create_user(inviter_tg_id, inviter_username)
    create_user(invited_tg_id, invited_username)
    
    # 1. Купон для приглашенного (скидка)
    invited_coupon = create_coupon(
        coupon_type='invited_discount',
        discount_percent=invited_discount_percent,
        stars_count=10,
        owner_tg_id=invited_tg_id,
        inviter_tg_id=inviter_tg_id,
        invited_tg_id=invited_tg_id,
        min_stars=10
    )
    
    # 2. Купон для пригласившего (награда)
    inviter_coupon = create_coupon(
        coupon_type='inviter_reward',
        discount_percent=inviter_reward_percent,
        stars_count=1,
        owner_tg_id=inviter_tg_id,
        inviter_tg_id=inviter_tg_id,
        invited_tg_id=invited_tg_id,
        min_stars=1
    )
    
    # Записываем в referrals
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO referrals(
            inviter_tg_id, invited_tg_id, inviter_coupon_code, 
            invited_coupon_code, status, created_at
        ) VALUES (?,?,?,?,?,?)
    """, (inviter_tg_id, invited_tg_id, inviter_coupon, invited_coupon, 
          'pending', now().isoformat()))
    
    cur.execute("UPDATE users SET total_invites = total_invites + 1 WHERE tg_id = ?", 
                (inviter_tg_id,))
    
    conn.commit()
    conn.close()
    
    return {
        'inviter_coupon': inviter_coupon,
        'invited_coupon': invited_coupon
    }

def complete_purchase(buyer_tg_id: str, stars_count: int, coupon_code: Optional[str] = None) -> Dict[str, Any]:
    
    # Убедимся, что пользователь существует
    create_user(buyer_tg_id)
    
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    
    used_discount_percent = 0
    
    if coupon_code:
        cur.execute("""
            SELECT discount_percent, min_stars, status, owner_tg_id, expires_at, code
            FROM coupons WHERE code = ?
        """, (coupon_code,))
        coupon = cur.fetchone()
        
        if not coupon:
            conn.close()
            return {'ok': False, 'reason': 'coupon_not_found'}
            
        discount_percent, min_stars, status, owner_tg_id, expires_at, code = coupon
        
        # Проверки купона
        if status != 'active':
            conn.close()
            return {'ok': False, 'reason': 'coupon_not_active'}
        if now() > datetime.datetime.fromisoformat(expires_at):
            conn.close()
            return {'ok': False, 'reason': 'coupon_expired'}
        
        # Проверка min_stars удалена по запросу
        
        if owner_tg_id != buyer_tg_id:
            conn.close()
            return {'ok': False, 'reason': 'coupon_belongs_to_another_user'}
            
        used_discount_percent = discount_percent
        
        # Помечаем купон использованным
        cur.execute("""
            UPDATE coupons 
            SET status = 'used', used_at = ? 
            WHERE code = ?
        """, (now().isoformat(), coupon_code))
        
        # Если это был купон приглашенного, обновляем статус реферрала
        cur.execute("""
            UPDATE referrals 
            SET status = 'completed', completed_at = ? 
            WHERE invited_coupon_code = ?
        """, (now().isoformat(), coupon_code))
    
    # Записываем покупку
    cur.execute("""
        INSERT INTO purchases(
            buyer_tg_id, stars_count, coupon_code, discount_percent, created_at
        ) VALUES (?,?,?,?,?)
    """, (buyer_tg_id, stars_count, coupon_code, used_discount_percent, now().isoformat()))
    
    cur.execute("UPDATE users SET total_purchases = total_purchases + 1 WHERE tg_id = ?",
                (buyer_tg_id,))
    
    conn.commit()
    conn.close()
    
    return {
        'ok': True,
        'stars_count': stars_count,
        'used_discount_percent': used_discount_percent
    }

# --- Admin helpers ---
def list_coupons():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            c.code, c.coupon_type, c.discount_percent, c.stars_count, c.min_stars,
            c.owner_tg_id,
            u_owner.tg_username as owner_username,
            c.inviter_tg_id,
            u_inviter.tg_username as inviter_username,
            c.invited_tg_id,
            u_invited.tg_username as invited_username,
            c.status,
            c.created_at, c.expires_at, c.used_at
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
