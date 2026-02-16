import streamlit as st
import datetime
import pandas as pd
import matplotlib.pyplot as plt
from sqlalchemy import create_engine, Column, Integer, String, Date, Float, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import bcrypt
from st_aggrid import AgGrid, GridUpdateMode
import calendar as cal
from fpdf import FPDF

# ---------------- DATABASE SETUP ----------------
Base = declarative_base()
engine = create_engine("sqlite:///expense_app.db", echo=False)
Session = sessionmaker(bind=engine)
session = Session()

# ---------------- TABLES ----------------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(String, unique=True)
    password = Column(String)
    join_date = Column(Date, default=datetime.date.today)
    expenses = relationship("Expense", back_populates="user")
    salaries = relationship("Salary", back_populates="user")

class Expense(Base):
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    date = Column(Date)
    category = Column(String)
    amount = Column(Float)
    note = Column(String)
    user = relationship("User", back_populates="expenses")

class Salary(Base):
    __tablename__ = "salary"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    month = Column(String)  # YYYY-MM
    salary = Column(Float)
    user = relationship("User", back_populates="salaries")

Base.metadata.create_all(engine)

# ---------------- HELPERS ----------------
def register_user(name, email, password):
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    new_user = User(name=name, email=email, password=hashed)
    session.add(new_user)
    session.commit()

def authenticate_user(email, password):
    user = session.query(User).filter_by(email=email).first()
    if user and bcrypt.checkpw(password.encode(), user.password):
        return user
    return None

def save_expense(user_id, date, category, amount, note):
    new_exp = Expense(user_id=user_id, date=date, category=category, amount=amount, note=note)
    session.add(new_exp)
    session.commit()

def save_salary(user_id, month, salary):
    exists = session.query(Salary).filter_by(user_id=user_id, month=month).first()
    if exists:
        st.warning("Salary already fixed for this month")
        return
    new_sal = Salary(user_id=user_id, month=month, salary=salary)
    session.add(new_sal)
    session.commit()
    st.success("Salary saved in database ✅")

def get_monthly_salary(user_id, month=None):
    if not month:
        month = datetime.date.today().strftime("%Y-%m")
    sal = session.query(Salary).filter_by(user_id=user_id, month=month).first()
    return sal.salary if sal else 0.0

def get_month_expenses(user_id, year, month):
    records = session.query(Expense).filter(
        Expense.user_id == user_id,
        Expense.date.between(
            datetime.date(year, month, 1),
            datetime.date(year, month, cal.monthrange(year, month)[1])
        )
    ).all()

    data = []
    for r in records:
        data.append({
            "Date": r.date.strftime("%Y-%m-%d"),  # ✅ FIX
            "Category": r.category,
            "Amount": r.amount,
            "Note": r.note,
            "ID": r.id
        })

    return pd.DataFrame(data)


def monthly_summary(user_id, year=None, month=None):
    if not year or not month:
        today = datetime.date.today()
        year, month = today.year, today.month

    df = get_month_expenses(user_id, year, month)
    if df.empty:
        return None

    total_expense = df["Amount"].sum()
    salary = get_monthly_salary(user_id, f"{year}-{month:02d}")
    remaining = salary - total_expense
    category_summary = df.groupby("Category")["Amount"].sum().to_dict()
    max_category = max(category_summary, key=category_summary.get) if category_summary else None

    return {
        "total_expense": total_expense,
        "salary": salary,
        "remaining": remaining,
        "max_category": max_category,
        "category_summary": category_summary,
        "df": df
    }

# ---------------- GRAPHS ----------------
def show_graphs(df):
    daily = df.groupby("Date")["Amount"].sum()
    st.markdown("### 📈 Daily Expense Trend")
    plt.figure(figsize=(8,4))
    daily.plot(marker='o')
    plt.xlabel("Date")
    plt.ylabel("Amount")
    st.pyplot(plt)

    category = df.groupby("Category")["Amount"].sum()
    st.markdown("### 📊 Category-wise Expense")
    plt.figure(figsize=(6,4))
    category.plot(kind="bar", color="skyblue")
    plt.ylabel("Amount")
    st.pyplot(plt)

    st.markdown("### 🥧 Expense Distribution by Category")
    plt.figure(figsize=(6,6))
    category.plot(kind="pie", autopct='%1.1f%%', startangle=90)
    plt.ylabel("")
    st.pyplot(plt)

# ---------------- SUMMARY ----------------
def show_summary(summary):
    st.markdown("### 💡 Month Summary")
    st.write(f"**Salary:** Rs.{summary['salary']}")
    st.write(f"**Total Expenses:** Rs.{summary['total_expense']}")
    st.write(f"**Remaining Salary:** Rs.{summary['remaining']}")
    st.write(f"**Highest Spending Category:** {summary['max_category']}")

# ---------------- ADVANCED INSIGHTS ----------------
def advanced_insights(month_summary):
    df = month_summary["df"]
    if df.empty: return
    daily_sum = df.groupby("Date")["Amount"].sum()
    st.markdown("### 🔎 Advanced Insights")
    st.write(f"Average daily spend: Rs.{daily_sum.mean():.2f}")
    st.write(f"Highest spending day: {daily_sum.idxmax()} → Rs.{daily_sum.max()}")
    st.write(f"Suggested saving category: {month_summary['max_category']} (try to reduce)")

# ---------------- ALERTS ----------------
def show_alerts(month_summary):
    df = month_summary["df"]
    if df.empty: return

    avg_daily = df.groupby("Date")["Amount"].sum().mean()
    high_days = df.groupby("Date")["Amount"].sum()
    high_days = high_days[high_days > avg_daily]
    if not high_days.empty:
        st.warning(f"⚠️ High spending days: {', '.join(high_days.index.astype(str))}")

    if month_summary['remaining'] < month_summary['salary'] * 0.1:
        st.warning("⚠️ Remaining salary is below 10%!")

# ---------------- PDF EXPORT ----------------
def export_pdf(user_name, month_summary, filename="monthly_report.pdf"):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, f"{user_name} - Monthly Expense Report", 0, 1, "C")
    pdf.set_font("Arial", "", 12)
    pdf.ln(5)
    pdf.cell(0, 10, f"Salary: Rs.{month_summary['salary']}", 0, 1)
    pdf.cell(0, 10, f"Total Expenses: Rs.{month_summary['total_expense']}", 0, 1)
    pdf.cell(0, 10, f"Remaining Salary: Rs.{month_summary['remaining']}", 0, 1)
    pdf.cell(0, 10, f"Highest Spending Category: {month_summary['max_category']}", 0, 1)
    pdf.ln(5)
    pdf.cell(0, 10, "Category-wise Expenses:", 0, 1)
    for cat, amt in month_summary['category_summary'].items():
        pdf.cell(0, 10, f"{cat}: Rs.{amt}", 0, 1)
    pdf.output(filename)
    return filename

# ---------------- SESSION ----------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user" not in st.session_state:
    st.session_state.user = None

# ---------------- UI ----------------
st.set_page_config(page_title="Expense Tracker", page_icon="💰")
st.title("💰 Monthly Expense & Salary Tracker")

# ---------------- LOGIN / REGISTER ----------------
if not st.session_state.logged_in:
    st.subheader("🔐 Login or Register")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    name = st.text_input("Name (only for new registration)")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Login"):
            user = authenticate_user(email, password)
            if user:
                st.success(f"Welcome back, {user.name}!")
                st.session_state.logged_in = True
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Login failed. Check email/password or register.")
    with col2:
        if st.button("Register"):
            if email and password and name:
                existing = session.query(User).filter_by(email=email).first()
                if existing:
                    st.error("User already exists. Login instead.")
                else:
                    register_user(name, email, password)
                    st.success("Registration successful! You can now login.")
            else:
                st.warning("Enter Name, Email and Password to register.")

# ---------------- AFTER LOGIN ----------------
else:
    user = st.session_state.user
    email = user.email
    name = user.name

    st.sidebar.title("👤 Profile")
    st.sidebar.write(name)
    st.sidebar.write(email)

    menu = st.sidebar.radio(
        "Menu",
        ["Calendar", "Salary", "Reports", "Logout"]
    )

    # ---------------- CALENDAR ----------------
    if menu == "Calendar":
        st.subheader("📅 Calendar & Day-wise Expenses")
        today = datetime.date.today()
        year = st.selectbox("Year", [today.year-1, today.year, today.year+1], index=1)
        month = st.selectbox("Month", list(range(1,13)), index=today.month-1)
        df_month = get_month_expenses(user.id, year, month)

        if not df_month.empty:
            st.markdown("### Edit / Delete Expenses")
            grid_response = AgGrid(
                df_month,
                editable=True,
                update_mode=GridUpdateMode.MODEL_CHANGED,
                fit_columns_on_grid_load=True
            )
            updated_df = grid_response['data']
            for idx, row in updated_df.iterrows():
                exp = session.query(Expense).filter_by(id=int(row['ID'])).first()
                if exp:
                    exp.date = datetime.datetime.strptime(row["Date"], "%Y-%m-%d").date()

                    exp.category = row['Category']
                    exp.amount = row['Amount']
                    exp.note = row['Note']
            session.commit()
            st.success("Expenses updated successfully ✅")
        else:
            st.info("No expenses for this month yet.")

        st.markdown("### Add New Expense")
        new_date = st.date_input("Date", datetime.date.today())
        new_cat = st.text_input("Category")
        new_amt = st.number_input("Amount", min_value=0.0, step=1.0)
        new_note = st.text_input("Note")
        if st.button("Add Expense"):
            save_expense(user.id, new_date, new_cat, new_amt, new_note)
            st.success("Expense added ✅")
            st.rerun()

    # ---------------- SALARY ----------------
    elif menu == "Salary":
        st.subheader("💼 Salary")
        month_str = datetime.date.today().strftime("%Y-%m")
        salary = get_monthly_salary(user.id, month_str)
        if salary > 0:
            st.success(f"Salary: Rs.{salary}")
        else:
            sal = st.number_input("Enter salary", min_value=0.0, step=1000.0)
            if st.button("Fix Salary"):
                save_salary(user.id, month_str, sal)

    # ---------------- REPORTS ----------------
    elif menu == "Reports":
        st.subheader("📊 Full Dashboard & Insights")
        today = datetime.date.today()
        year, month = today.year, today.month
        summary = monthly_summary(user.id, year, month)

        if not summary:
            st.info("No expenses for this month yet!")
        else:
            show_summary(summary)
            show_alerts(summary)
            show_graphs(summary["df"])
            advanced_insights(summary)

            # CSV Export
            csv = summary["df"].to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download CSV",
                csv,
                f"{year}-{month:02d}_expenses.csv",
                "text/csv"
            )

            # PDF Export
            pdf_file = export_pdf(user.name, summary, f"{year}-{month:02d}_report.pdf")
            with open(pdf_file, "rb") as f:
                st.download_button("Download PDF Report", f, f"{year}-{month:02d}_report.pdf")

    # ---------------- LOGOUT ----------------
    elif menu == "Logout":
        st.session_state.logged_in = False
        st.session_state.user = None
        st.rerun()

