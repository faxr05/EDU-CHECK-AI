import streamlit as st
import sqlite3
import pandas as pd
import google.generativeai as genai
import os
from PIL import Image
import plotly.express as px

# --- KONFIGURATSIYA ---
if not os.path.exists('uploads'):
    os.makedirs('uploads')

# Gemini API sozlamasi
# Streamlit secrets orqali kalitni o'qish
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Gemini API Keyni kiriting:", type="password")

if api_key:
    genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.5-flash') # Tavsiya etilgan stabil model

def get_connection():
    conn = sqlite3.connect('smart_classroom.db', check_same_thread=False)
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY, username TEXT, password TEXT, role TEXT, class_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS classes 
                 (id INTEGER PRIMARY KEY, class_name TEXT, teacher_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tasks 
                 (id INTEGER PRIMARY KEY, class_id INTEGER, title TEXT, description TEXT, 
                  task_image_path TEXT, criteria_text TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS submissions 
                 (id INTEGER PRIMARY KEY, task_id INTEGER, student_id INTEGER, answer_text TEXT, 
                  answer_image_path TEXT, ai_grade INTEGER, ai_feedback TEXT, status TEXT)''')
    conn.commit()

init_db()

# --- YORDAMCHI FUNKSIYALAR ---
def login_user(username, password):
    conn = get_connection()
    return pd.read_sql(f"SELECT * FROM users WHERE username='{username}' AND password='{password}'", conn)

def get_classes():
    conn = get_connection()
    return pd.read_sql("SELECT * FROM classes", conn)

# --- SESSION STATE ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user = None

st.set_page_config(page_title="EDU CHECK AI", layout="wide")

if not st.session_state.logged_in:
    tab1, tab2 = st.tabs(["Kirish", "Ro'yxatdan o'tish"])
    
    with tab1:
        st.header("Tizimga kirish")
        user_in = st.text_input("Login")
        pass_in = st.text_input("Parol", type="password")
        if st.button("Kirish"):
            res = login_user(user_in, pass_in)
            if not res.empty:
                st.session_state.logged_in = True
                st.session_state.user = res.iloc[0]
                st.rerun()
            else:
                st.error("Login yoki parol xato!")

    with tab2:
        st.header("Yangi hisob ochish")
        new_user = st.text_input("Yangi login")
        new_pass = st.text_input("Yangi parol", type="password")
        role = st.selectbox("Rolingiz", ["Teacher", "Student"])
        
        class_id = None
        if role == "Student":
            classes_df = get_classes()
            if not classes_df.empty:
                class_choice = st.selectbox("Sinfingizni tanlang", classes_df['class_name'].tolist())
                class_id = int(classes_df[classes_df['class_name'] == class_choice]['id'].values[0])
            else:
                st.warning("Hali sinflar yaratilmagan.")

        if st.button("Ro'yxatdan o'tish"):
            conn = get_connection()
            c = conn.cursor()
            c.execute("INSERT INTO users (username, password, role, class_id) VALUES (?,?,?,?)", 
                      (new_user, new_pass, role, class_id))
            conn.commit()
            st.success("Muvaffaqiyatli o'tdingiz!")

else:
    user = st.session_state.user
    st.sidebar.title(f"Xush kelibsiz, {user['username']}")
    if st.sidebar.button("Chiqish"):
        st.session_state.logged_in = False
        st.rerun()

    # --- USTOZ MODULI ---
    if user['role'] == "Teacher":
        menu = st.sidebar.radio("Menyu", ["Sinf boshqaruvi", "Topshiriq berish", "Statistika"])

        if menu == "Sinf boshqaruvi":
            st.header("Sinf yaratish")
            c_name = st.text_input("Sinf nomi (masalan: 10-A)")
            if st.button("Sinfni saqlash"):
                conn = get_connection()
                c = conn.cursor()
                c.execute("INSERT INTO classes (class_name, teacher_id) VALUES (?,?)", (c_name, user['id']))
                conn.commit()
                st.success(f"{c_name} sinfi ochildi.")

        elif menu == "Topshiriq berish":
            st.header("Yangi topshiriq")
            classes_df = get_classes()
            if not classes_df.empty:
                target_class = st.selectbox("Qaysi sinfga?", classes_df['class_name'].tolist())
                t_id = classes_df[classes_df['class_name'] == target_class]['id'].values[0]
                
                title = st.text_input("Mavzu nomi")
                desc = st.text_area("Topshiriq matni")
                criteria = st.text_area("AI uchun baholash mezoni")
                img = st.file_uploader("Rasm yuklash", type=['png', 'jpg', 'jpeg'])
                
                if st.button("Yuborish"):
                    path = ""
                    if img:
                        path = f"uploads/task_{img.name}"
                        with open(path, "wb") as f: f.write(img.getbuffer())
                    
                    conn = get_connection()
                    c = conn.cursor()
                    c.execute("INSERT INTO tasks (class_id, title, description, task_image_path, criteria_text) VALUES (?,?,?,?,?)",
                              (int(t_id), title, desc, path, criteria))
                    conn.commit()
                    st.success("Topshiriq yuborildi!")
            else:
                st.error("Avval sinf yarating!")

        elif menu == "Statistika":
            st.header("📊 O'zlashtirish va Javoblar Tahlili")
            conn = get_connection()
            
            classes_df = get_classes()
            if not classes_df.empty:
                selected_class_name = st.selectbox("Sinfni tanlang:", classes_df['class_name'].tolist())
                selected_class_id = classes_df[classes_df['class_name'] == selected_class_name]['id'].values[0]
                
                # Murakkab query: User va Submissionlarni bog'lash
                query = f"""
                    SELECT u.username, s.ai_grade, t.title as vazifa, s.status, 
                           s.answer_text, s.answer_image_path, s.ai_feedback
                    FROM submissions s 
                    JOIN users u ON s.student_id = u.id 
                    JOIN tasks t ON s.task_id = t.id
                    WHERE u.class_id = {selected_class_id}
                """
                df = pd.read_sql(query, conn)
                
                if not df.empty:
                    df['ai_grade'] = pd.to_numeric(df['ai_grade'], errors='coerce').fillna(0)
                    
                    # 1. Grafik
                    st.subheader("📈 Baholar Grafigi")
                    fig = px.bar(df, x='username', y='ai_grade', color='ai_grade', 
                                 hover_data=['vazifa'], title="O'quvchilar natijalari")
                    st.plotly_chart(fig, use_container_width=True)

                    # 2. Batafsil ko'rish
                    st.subheader("🔍 O'quvchilar javoblari va AI xulosalari")
                    for index, row in df.iterrows():
                        with st.expander(f"👤 {row['username']} - {row['vazifa']}"):
                            c1, c2 = st.columns(2)
                            with c1:
                                st.markdown("**O'quvchi javobi:**")
                                st.write(row['answer_text'] if row['answer_text'] else "Matn yo'q")
                                if row['answer_image_path'] and os.path.exists(row['answer_image_path']):
                                    st.image(row['answer_image_path'], caption="Yuborilgan rasm", width=300)
                            with c2:
                                st.success(f"**AI Bahosi:** {row['ai_grade']} ball")
                                st.info(f"**AI Izohi:**\n{row['ai_feedback']}")
                else:
                    st.warning("Ushbu sinfda hali hech kim javob topshirmagan.")
            else:
                st.error("Sinflar mavjud emas.")

    # --- O'QUVCHI MODULI ---
    elif user['role'] == "Student":
        st.header("📝 Sizning topshiriqlaringiz")
        conn = get_connection()
        tasks_df = pd.read_sql(f"SELECT * FROM tasks WHERE class_id={user['class_id']}", conn)
        
        for index, row in tasks_df.iterrows():
            with st.expander(f"📌 {row['title']}"):
                st.write(row['description'])
                if row['task_image_path'] and os.path.exists(row['task_image_path']):
                    st.image(row['task_image_path'], width=300)
                
                ans_text = st.text_area("Javobingiz", key=f"t_{row['id']}")
                ans_img = st.file_uploader("Rasm yuborish", type=['png', 'jpg', 'jpeg'], key=f"i_{row['id']}")
                
                if st.button("AI Tahliliga yuborish", key=f"b_{row['id']}"):
                    with st.spinner("AI tekshirmoqda..."):
                        img_path = ""
                        ai_content = [f"Vazifa: {row['description']}\nMezon: {row['criteria_text']}\nJavob: {ans_text}"]
                        
                        if ans_img:
                            img_path = f"uploads/ans_{ans_img.name}"
                            with open(img_path, "wb") as f: f.write(ans_img.getbuffer())
                            ai_content.append(Image.open(ans_img))

                        prompt = """Bahola: Baho: [0-100] va Izoh: [fikr] formatida qaytar."""
                        
                        try:
                            response = model.generate_content([prompt] + ai_content)
                            res_text = response.text
                            
                            # Bahoni qidirish (regex o'rniga oddiy split)
                            grade = 0
                            try:
                                if "Baho:" in res_text:
                                    grade_part = res_text.split("Baho:")[1].split()[0]
                                    grade = "".join(filter(str.isdigit, grade_part))
                            except: grade = 0

                            c = conn.cursor()
                            c.execute("INSERT INTO submissions (task_id, student_id, answer_text, answer_image_path, ai_grade, ai_feedback, status) VALUES (?,?,?,?,?,?,?)",
                                      (int(row['id']), int(user['id']), ans_text, img_path, grade, res_text, "Checked"))
                            conn.commit()
                            st.success(f"Natija: {res_text}")
                        except Exception as e:
                            st.error(f"Xato: {e}")