import sqlite3


def check(number: str, fz=None) -> bool:
    conn = sqlite3.connect(r"C:\Mr.Krabs\pythonProject\tracking.db")
    cursor = conn.cursor()

    number = number.strip()  # Страхуемся от пробелов
    print(f"[DEBUG] Проверка номера: {number}, fz: {fz}")

    if fz:
        # Если указан fz, проверяем по номеру И по fz
        cursor.execute(
            "SELECT number FROM zakupkigov WHERE number = ? AND fz = ?",
            (number, fz)
            )
    else:
        # Если fz не указан, проверяем только по номеру
        cursor.execute(
            "SELECT number FROM zakupkigov WHERE number = ?",
            (number,)
            )

    exists = cursor.fetchone() is not None
    conn.close()

    print(f"[DEBUG] Результат проверки: {exists}")
    return exists



def clear_zakupkigov():
    """Очищает все записи из таблицы zakupkigov (но оставляет саму таблицу)"""
    conn = sqlite3.connect(r"C:\Mr.Krabs\pythonProject\tracking.db")
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM zakupkigov")
        conn.commit()
        print("✅ Все записи из таблицы zakupkigov удалены")
    except Exception as e:
        print(f"❌ Ошибка при очистке таблицы: {e}")
    finally:
        conn.close()

def save(number, fz=None):
    conn = sqlite3.connect(r"C:\Mr.Krabs\pythonProject\tracking.db")
    cursor = conn.cursor()

    try:
        # Если fz пустой или None, вставляем NULL
        if not fz:
            cursor.execute("INSERT OR IGNORE INTO zakupkigov (fz, number) VALUES (0, ?)", (number,))
        else:
            cursor.execute("INSERT OR IGNORE INTO zakupkigov (fz, number) VALUES (?, ?)", (fz, number))

        conn.commit()
    except Exception as e:
        print(f"❌ Ошибка сохранения в БД: {e}")
    finally:
        conn.close()

def get_client_users():
    conn = sqlite3.connect(r"C:\Mr.Krabs\pythonProject\tracking.db")
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM init_clients")

    result = cursor.fetchall()

    conn.close()

    # Если результат найден, возвращаем user_id, иначе None
    return result if result else []

def add_init_client(user_id,chat_id,contact_username,contact_name,contact_phone):

    conn = sqlite3.connect(r"C:\Mr.Krabs\pythonProject\tracking.db")
    cursor = conn.cursor()

    cursor.execute("""
          INSERT OR IGNORE INTO init_clients (user_id, chat_id, contact_username, contact_name, contact_phone) 
          VALUES (?, ?, ?, ?, ?)
      """, (user_id, chat_id, contact_username, contact_name, contact_phone))

    conn.commit()
    conn.close()


