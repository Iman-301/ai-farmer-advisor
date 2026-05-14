import streamlit as st
import sqlite3
import pandas as pd
import bcrypt
import chromadb
from chromadb.utils import embedding_functions
import os
import time

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "advisor.db")
SESSION_TIMEOUT_SECONDS = 3600  # 1 hour

# ── ChromaDB ──────────────────────────────────────────────────────────────────
chroma_client = chromadb.PersistentClient(path=os.path.join(DATA_DIR, "chroma_db"))
sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="paraphrase-multilingual-MiniLM-L12-v2"
)
collection = chroma_client.get_or_create_collection(
    name="agronomy_kb",
    embedding_function=sentence_transformer_ef
)


# ── DB Helpers ────────────────────────────────────────────────────────────────
def get_db_connection():
    return sqlite3.connect(DB_PATH)


def setup_admin():
    """Seed a default admin user if none exist."""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM admin_users")
        if c.fetchone()[0] == 0:
            pw_hash = bcrypt.hashpw("admin".encode("utf-8"), bcrypt.gensalt())
            c.execute(
                "INSERT INTO admin_users (username, password_hash, role) VALUES (?, ?, ?)",
                ("admin", pw_hash.decode("utf-8"), "admin")
            )
            conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def login_user(username: str, password: str):
    """Returns the user's role string if credentials are valid, else None."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT password_hash, role FROM admin_users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if row:
        stored_hash = row[0].encode("utf-8")
        if bcrypt.checkpw(password.encode("utf-8"), stored_hash):
            return row[1]
    return None


# ── Session Utilities ─────────────────────────────────────────────────────────
def check_session_timeout():
    """Log out user if the session has exceeded SESSION_TIMEOUT_SECONDS."""
    if st.session_state.get("logged_in") and "login_time" in st.session_state:
        elapsed = time.time() - st.session_state["login_time"]
        if elapsed > SESSION_TIMEOUT_SECONDS:
            st.session_state.logged_in = False
            st.session_state.role = ""
            st.warning("Session expired. Please log in again.")
            st.rerun()


# ── App Setup ─────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Farmer Advisor Dashboard", layout="wide")

# Initialize session state
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = ""
    st.session_state.login_time = None

setup_admin()
check_session_timeout()

# ── Login Page ────────────────────────────────────────────────────────────────
if not st.session_state.logged_in:
    st.title("🌾 Farmer Advisor — Admin / Expert Portal")
    st.markdown("---")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
        if submitted:
            role = login_user(username, password)
            if role:
                st.session_state.logged_in = True
                st.session_state.role = role
                st.session_state.login_time = time.time()
                st.rerun()
            else:
                st.error("Invalid credentials. Please try again.")

# ── Main Dashboard ─────────────────────────────────────────────────────────────
else:
    st.sidebar.title("🌾 Navigation")
    pages = [
        "Call Logs & Farmers",
        "Escalation Queue",
        "Market Prices",
        "Knowledge Base",
        "Alerts & Forecasts",
    ]
    choice = st.sidebar.radio("Go to", pages)
    st.sidebar.markdown("---")
    st.sidebar.write(f"Logged in as: **{st.session_state.role}**")

    # Show session time remaining
    if st.session_state.login_time:
        remaining = SESSION_TIMEOUT_SECONDS - int(time.time() - st.session_state.login_time)
        mins, secs = divmod(max(remaining, 0), 60)
        st.sidebar.caption(f"Session expires in: {mins}m {secs}s")

    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.login_time = None
        st.rerun()

    # ── Page: Call Logs & Farmers ─────────────────────────────────────────────
    if choice == "Call Logs & Farmers":
        st.title("📋 Call Logs & Registered Farmers")

        st.subheader("Registered Farmers")
        conn = get_db_connection()
        try:
            df_farmers = pd.read_sql_query(
                "SELECT * FROM farmers ORDER BY registered_at DESC", conn
            )
            st.dataframe(df_farmers, use_container_width=True)
        except Exception:
            st.warning("Farmers table not found or empty.")

        st.subheader("Recent Call Records")
        try:
            df_calls = pd.read_sql_query(
                """SELECT c.id, c.session_id, c.phone_number, f.name,
                          c.duration, c.timestamp, c.recording_path
                   FROM call_records c
                   LEFT JOIN farmers f ON c.phone_number = f.phone_number
                   ORDER BY c.timestamp DESC LIMIT 50""",
                conn
            )
            if df_calls.empty:
                st.info("No calls recorded yet.")
            else:
                st.dataframe(df_calls, use_container_width=True)
                st.markdown("### 🔊 Playback Audio")
                selected_session = st.selectbox(
                    "Select Session ID to play audio:", df_calls["session_id"].tolist()
                )
                if selected_session:
                    row = df_calls[df_calls["session_id"] == selected_session].iloc[0]
                    audio_path = row["recording_path"]
                    if os.path.exists(audio_path):
                        st.audio(audio_path)
                    else:
                        st.warning(f"Audio file not found: {audio_path}")
        except Exception as e:
            st.warning(f"Could not load call records: {e}")
        finally:
            conn.close()

    # ── Page: Escalation Queue ─────────────────────────────────────────────────
    elif choice == "Escalation Queue":
        st.title("🚨 Escalation Queue")
        conn = get_db_connection()
        try:
            df = pd.read_sql_query(
                "SELECT * FROM escalated_queries ORDER BY timestamp DESC", conn
            )
            if df.empty:
                st.info("No escalations found.")
            else:
                st.dataframe(df, use_container_width=True)
                ticket_id = st.number_input("Resolve Ticket ID:", min_value=1, step=1)
                if st.button("✅ Mark Resolved"):
                    c = conn.cursor()
                    c.execute(
                        "UPDATE escalated_queries SET status='resolved' WHERE id=?",
                        (int(ticket_id),)
                    )
                    conn.commit()
                    st.success(f"Ticket #{ticket_id} marked as resolved.")
                    st.rerun()
        except Exception as e:
            st.error(f"Error loading escalation queue: {e}")
        finally:
            conn.close()

    # ── Page: Market Prices ────────────────────────────────────────────────────
    elif choice == "Market Prices":
        st.title("💰 Manage Market Prices")

        with st.form("add_market_price"):
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                crop = st.text_input("Crop Name (e.g., Teff)")
            with col2:
                region = st.text_input("Region (e.g., Addis Ababa)")
            with col3:
                price = st.number_input("Price (ETB)", min_value=0.0, format="%.2f")
            with col4:
                unit = st.text_input("Unit (e.g., Kg, Quintal)")
            submitted = st.form_submit_button("➕ Add / Update Price")
            if submitted and crop and region and unit:
                conn = get_db_connection()
                c = conn.cursor()
                c.execute(
                    "INSERT INTO market_prices (crop_name, region, price, unit) VALUES (?, ?, ?, ?)",
                    (crop.strip(), region.strip(), price, unit.strip())
                )
                conn.commit()
                conn.close()
                st.success(f"Price added for {crop} in {region}.")
                st.rerun()

        st.subheader("Current Price Database")
        conn = get_db_connection()
        try:
            df = pd.read_sql_query(
                "SELECT id, crop_name, region, price, unit, updated_at FROM market_prices ORDER BY updated_at DESC",
                conn
            )
            st.dataframe(df, use_container_width=True)
        except Exception as e:
            st.warning(f"Could not load prices: {e}")
        finally:
            conn.close()

    # ── Page: Knowledge Base ───────────────────────────────────────────────────
    elif choice == "Knowledge Base":
        st.title("📚 Manage Knowledge Base (ChromaDB)")

        if st.session_state.role != "admin":
            st.error("🔒 Permission Denied: Only Admins can modify the Knowledge Base.")
        else:
            st.subheader("➕ Add New Entry")
            with st.form("add_kb_entry"):
                intent = st.text_input("Intent tag (e.g., crop_disease, fertilizer_wheat)")
                response = st.text_area("Amharic response text", height=120)
                submitted = st.form_submit_button("Add to Vector Store")
                if submitted and intent and response:
                    doc_id = f"kb_{uuid.uuid4() if True else collection.count() + 1}"
                    import uuid as _uuid
                    doc_id = f"kb_{_uuid.uuid4()}"
                    collection.add(
                        documents=[response],
                        metadatas=[{"intent": intent}],
                        ids=[doc_id]
                    )
                    st.success(f"Added entry ID: `{doc_id}`")
                    st.rerun()

            st.subheader(f"📖 Existing Entries ({collection.count()} total)")
            try:
                if collection.count() > 0:
                    all_entries = collection.get(include=["documents", "metadatas"])
                    rows = []
                    for doc_id, doc, meta in zip(
                        all_entries["ids"],
                        all_entries["documents"],
                        all_entries["metadatas"]
                    ):
                        rows.append({
                            "ID": doc_id,
                            "Intent": meta.get("intent", ""),
                            "Response (preview)": doc[:120] + ("…" if len(doc) > 120 else "")
                        })
                    df_kb = pd.DataFrame(rows)
                    st.dataframe(df_kb, use_container_width=True)

                    st.subheader("🗑️ Delete Entry")
                    del_id = st.text_input("Enter Entry ID to delete")
                    if st.button("Delete") and del_id:
                        try:
                            collection.delete(ids=[del_id])
                            st.success(f"Deleted entry: `{del_id}`")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Delete failed: {e}")
                else:
                    st.info("Knowledge Base is empty. Add some entries above.")
            except Exception as e:
                st.error(f"Could not load KB entries: {e}")

    # ── Page: Alerts & Forecasts ───────────────────────────────────────────────
    elif choice == "Alerts & Forecasts":
        st.title("📡 Predictive Alerts & Broadcast")

        if st.session_state.role != "admin":
            st.error("🔒 Permission Denied: Only Admins can broadcast alerts.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("📢 Broadcast New Alert")
                with st.form("add_alert"):
                    target_region = st.selectbox(
                        "Target Region",
                        ["all", "Addis Ababa", "Oromia", "Amhara", "SNNPR", "Tigray", "Sidama", "Afar"]
                    )
                    alert_message = st.text_area("Alert Message (Amharic)", height=100)
                    severity = st.selectbox("Severity", ["info", "warning", "critical"])
                    submitted = st.form_submit_button("📣 Broadcast")
                    if submitted and alert_message:
                        conn = get_db_connection()
                        c = conn.cursor()
                        c.execute(
                            "INSERT INTO alerts (target_region, alert_message, severity) VALUES (?, ?, ?)",
                            (target_region, alert_message, severity)
                        )
                        conn.commit()
                        conn.close()
                        st.success(f"Alert broadcast to **{target_region}** region!")
                        st.rerun()

            with col2:
                st.subheader("📊 Alert Summary by Region")
                conn = get_db_connection()
                try:
                    df_alerts = pd.read_sql_query(
                        """SELECT target_region, severity, COUNT(*) as count
                           FROM alerts
                           GROUP BY target_region, severity""",
                        conn
                    )
                    if not df_alerts.empty:
                        pivot = df_alerts.pivot(
                            index="target_region", columns="severity", values="count"
                        ).fillna(0)
                        st.bar_chart(pivot)
                    else:
                        st.info("No alerts yet.")
                except Exception:
                    st.info("No alert data available.")
                finally:
                    conn.close()

                st.markdown("**Estimated Reach:** ~45,000 farmers in active warning zones.")

        st.subheader("📋 Recent Broadcasts")
        conn = get_db_connection()
        try:
            df = pd.read_sql_query(
                """SELECT id, target_region, alert_message, severity, created_at
                   FROM alerts ORDER BY created_at DESC LIMIT 50""",
                conn
            )
            st.dataframe(df, use_container_width=True)
        except Exception:
            st.warning("Could not load alerts. Check database schema.")
        finally:
            conn.close()
