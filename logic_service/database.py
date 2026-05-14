import chromadb
from chromadb.utils import embedding_functions
import json
import sqlite3
import os

# Initialize Vector DB for RAG
DATA_DIR = os.environ.get("DATA_DIR", "/data")
chroma_client = chromadb.PersistentClient(path=os.path.join(DATA_DIR, "chroma_db"))
# Using an Amharic-optimized sentence transformer for embeddings
sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="rasyosef/roberta-amharic-text-embedding-base")

collection = chroma_client.get_or_create_collection(name="agronomy_kb", embedding_function=sentence_transformer_ef)

def init_kb():
    if collection.count() == 0:
        # Load mock KB
        if os.path.exists("mock_kb.json"):
            with open("mock_kb.json", "r", encoding="utf-8") as f:
                kb_data = json.load(f)
                
            documents = []
            metadatas = []
            ids = []
            
            for i, (intent, response) in enumerate(kb_data.items()):
                if intent == "unknown":
                    continue
                # Mapping intent keywords to the Amharic response
                documents.append(response)
                metadatas.append({"intent": intent})
                ids.append(str(i))
                
            collection.add(documents=documents, metadatas=metadatas, ids=ids)
            print("Knowledge Base Initialized.")

DB_PATH = os.path.join(DATA_DIR, "advisor.db")

# Initialize SQLite for all entities
def init_db():
    # Ensure the parent directory exists (important for RAG-only/local modes)
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Escalated Queries
    c.execute('''CREATE TABLE IF NOT EXISTS escalated_queries
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  query TEXT NOT NULL,
                  context TEXT,
                  status TEXT DEFAULT 'pending',
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')

    # Farmers Profile
    c.execute('''CREATE TABLE IF NOT EXISTS farmers
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  phone_number TEXT UNIQUE NOT NULL,
                  name TEXT,
                  location TEXT,
                  preferred_language TEXT DEFAULT 'am',
                  registered_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')

    # Conversation History
    c.execute('''CREATE TABLE IF NOT EXISTS conversation_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  phone_number TEXT,
                  session_id TEXT NOT NULL,
                  role TEXT NOT NULL,
                  message TEXT NOT NULL,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')

    # Market Prices
    c.execute('''CREATE TABLE IF NOT EXISTS market_prices
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  crop_name TEXT NOT NULL,
                  region TEXT NOT NULL,
                  price REAL NOT NULL,
                  unit TEXT NOT NULL,
                  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')

    # Admin Users
    c.execute('''CREATE TABLE IF NOT EXISTS admin_users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password_hash TEXT NOT NULL,
                  role TEXT NOT NULL,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')

    # Alerts / Forecasts
    c.execute('''CREATE TABLE IF NOT EXISTS alerts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  target_region TEXT NOT NULL,
                  alert_message TEXT NOT NULL,
                  severity TEXT DEFAULT 'warning',
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')

    # Session States (For Multi-turn / Safety Confirmations)
    c.execute('''CREATE TABLE IF NOT EXISTS session_states
                 (session_id TEXT PRIMARY KEY,
                  current_state TEXT NOT NULL,
                  pending_action TEXT,
                  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')

    # Call Records
    c.execute('''CREATE TABLE IF NOT EXISTS call_records
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT UNIQUE NOT NULL,
                  phone_number TEXT NOT NULL,
                  recording_path TEXT NOT NULL,
                  duration INTEGER NOT NULL,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')

    conn.commit()
    conn.close()

def add_to_escalation(query: str, context: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO escalated_queries (query, context) VALUES (?, ?)", (query, context))
    conn.commit()
    conn.close()

def log_conversation(phone_number: str, session_id: str, role: str, message: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO conversation_history (phone_number, session_id, role, message) VALUES (?, ?, ?, ?)", 
              (phone_number, session_id, role, message))
    conn.commit()
    conn.close()

def get_conversation_history(session_id: str, limit: int = 5):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role, message FROM conversation_history WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?", (session_id, limit))
    history = c.fetchall()
    conn.close()
    return list(reversed(history))

def get_market_price(crop_name: str, region: str = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if region:
        c.execute(
            "SELECT price, unit, updated_at FROM market_prices WHERE crop_name = ? AND region = ? ORDER BY updated_at DESC LIMIT 1",
            (crop_name, region)
        )
    else:
        c.execute(
            "SELECT price, unit, updated_at FROM market_prices WHERE crop_name = ? ORDER BY updated_at DESC LIMIT 1",
            (crop_name,)
        )
    result = c.fetchone()
    conn.close()
    return result  # (price, unit, updated_at) or None

def register_farmer(phone_number: str, name: str, location: str, preferred_language: str = 'am'):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        # SQLite UPSERT equivalent (since sqlite 3.24)
        c.execute("INSERT INTO farmers (phone_number, name, location, preferred_language) VALUES (?, ?, ?, ?) ON CONFLICT(phone_number) DO UPDATE SET name=excluded.name, location=excluded.location, preferred_language=excluded.preferred_language", 
                  (phone_number, name, location, preferred_language))
        conn.commit()
    except Exception as e:
        print(f"Error registering farmer: {e}")
    finally:
        conn.close()

def get_farmer_profile(phone_number: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, location, preferred_language, registered_at FROM farmers WHERE phone_number = ?", (phone_number,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"phone_number": phone_number, "name": row[0], "location": row[1], "preferred_language": row[2], "registered_at": row[3]}
    return None

def create_alert(target_region: str, alert_message: str, severity: str = "warning"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO alerts (target_region, alert_message, severity) VALUES (?, ?, ?)", 
              (target_region, alert_message, severity))
    conn.commit()
    conn.close()

def get_alerts_for_region(region: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT alert_message, severity FROM alerts WHERE target_region = ? OR target_region = 'all' ORDER BY created_at DESC", (region,))
    alerts = c.fetchall()
    conn.close()
    return alerts

def set_session_state(session_id: str, current_state: str, pending_action: str = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO session_states (session_id, current_state, pending_action) VALUES (?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET current_state=excluded.current_state, pending_action=excluded.pending_action, updated_at=CURRENT_TIMESTAMP", 
                  (session_id, current_state, pending_action))
        conn.commit()
    except Exception as e:
        print(f"Error setting session state: {e}")
    finally:
        conn.close()

def get_session_state(session_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT current_state, pending_action FROM session_states WHERE session_id = ?", (session_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"current_state": row[0], "pending_action": row[1]}
    return None

def insert_call_record(session_id: str, phone_number: str, recording_path: str, duration: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO call_records (session_id, phone_number, recording_path, duration) VALUES (?, ?, ?, ?)",
                  (session_id, phone_number, recording_path, duration))
        conn.commit()
    except Exception as e:
        print(f"Error inserting call record: {e}")
    finally:
        conn.close()

init_kb()
init_db()
