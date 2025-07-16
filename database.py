import sqlite3

def init_db():
    conn = sqlite3.connect(r"C:\Mr.Krabs\pythonProject\tracking.db")
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS zakupkigov (
            fz TEXT NOT NULL,      
            number TEXT NOT NULL,
            PRIMARY KEY (fz, number)
        )
    ''')

    # Таблица для инициализированных клиентов
    cursor.execute("""
          CREATE TABLE IF NOT EXISTS init_clients (
              user_id INTEGER PRIMARY KEY,
              chat_id TEXT,
              contact_username TEXT,
              contact_name TEXT,
              contact_phone TEXT
          )
      """)

    conn.commit()
    conn.close()

init_db()
