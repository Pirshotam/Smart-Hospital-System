# Smart Hospital Bed & Emergency Capacity System

A full-stack hospital capacity management system built with **Streamlit**, **FastAPI**, and **MySQL**. The system helps manage hospital information, bed capacity, emergency requests, hospital matching, and reservations.

## Tech Stack

* **Frontend:** Streamlit
* **Backend:** FastAPI
* **Database:** MySQL 8
* **API Server:** Uvicorn
* **Database Driver:** PyMySQL
* **Language:** Python

---

## Project Structure

```text
smart-hospital-system/
│
├── schema.sql
│
├── backend/
│   ├── main.py
│   ├── database.py
│   ├── seed.py
│   ├── requirements.txt
│   └── services/
│       ├── __init__.py
│       ├── matcher.py
│       └── reservations.py
│
└── frontend/
    ├── app.py
    └── requirements.txt
```

---

# Requirements

Before running the project, make sure you have:

* Python 3.10 or newer
* MySQL 8
* Git

Check your installations:

```bash
python --version
mysql --version
git --version
```

# 1. Clone the Repository

Clone the GitHub repository:

```bash
git clone https://github.com/Pirshotam/Smart-Hospital-System.git
```

Move into the project directory:

```bash
cd Smart-Hospital-System
```

---

# 2. Install Backend Dependencies

Go to the backend directory:

```bash
cd backend
```

Install the required packages:

```bash
pip install -r requirements.txt
```

Return to the project root:

```bash
cd ..
```

---

# 3. Install Frontend Dependencies

Go to the frontend directory:

```bash
cd frontend
```

Install the required packages:

```bash
pip install -r requirements.txt
```

Return to the project root:

```bash
cd ..
```

---

# 4. Set Up MySQL Database

Make sure MySQL 8 is installed and running.

Open MySQL:

```bash
mysql -u root -p
```

Create the database:

```sql
CREATE DATABASE hospital_capacity;
```

Exit MySQL:

```sql
EXIT;
```

---

# 5. Configure Database Connection

The backend uses environment variables for the database connection.

Configure the following values according to your MySQL installation:

```text
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=hospital_capacity
```

Replace `your_mysql_password` with your actual MySQL password.

**Do not upload your actual database password to GitHub.**

---

# 6. Create the Database Tables

From the project root, import the SQL schema:

```bash
mysql -u root -p hospital_capacity < schema.sql
```

Enter your MySQL password when prompted.

This creates the tables required by the application.

Alternatively, you can open `schema.sql` in MySQL Workbench and execute it against the `hospital_capacity` database.

---

# 7. Seed the Database

The project includes a seed script containing initial/demo hospital data.

Go to the backend directory:

```bash
cd backend
```

Run:

```bash
python seed.py
```

This populates the database with the sample data required for testing the application.

Return to the project root:

```bash
cd ..
```

---

# 8. Start the FastAPI Backend

Open a terminal in the `backend` directory:

```bash
cd backend
```

Start the FastAPI server:

```bash
uvicorn main:app --reload
```

You should see something similar to:

```text
Uvicorn running on http://127.0.0.1:8000
```

The backend API is now running at:

```text
http://localhost:8000
```

## API Documentation

FastAPI automatically provides interactive API documentation.

Open:

```text
http://localhost:8000/docs
```

Keep this terminal running.

---

# 9. Start the Streamlit Frontend

Open a **second terminal**.

Go to the frontend directory:

```bash
cd frontend
```

Start Streamlit:

```bash
streamlit run app.py
```

You should see:

```text
Local URL: http://localhost:8501
```

Open the application in your browser:

```text
http://localhost:8501
```

Keep both terminals running:

```text
Terminal 1:
FastAPI → http://localhost:8000

Terminal 2:
Streamlit → http://localhost:8501
```

---

# 10. How the Application Works

The application follows this architecture:

```text
                    User
                     |
                     v
             Streamlit Frontend
             localhost:8501
                     |
                     | HTTP requests
                     v
              FastAPI Backend
              localhost:8000
                     |
          +----------+----------+
          |                     |
          v                     v
     Service Logic          Database
 matcher.py             database.py
 reservations.py             |
                              v
                           MySQL 8
```

The Streamlit frontend communicates with the FastAPI backend through HTTP requests.

The FastAPI backend handles API requests, business logic, and database operations.

The backend services provide specialized functionality such as hospital matching and reservations.

MySQL stores the application's persistent data.

---

# Troubleshooting

## Streamlit says "Cannot reach the backend"

Make sure the FastAPI server is running.

Check:

```text
http://localhost:8000/docs
```

If the API documentation doesn't open, start the backend:

```bash
cd backend
uvicorn main:app --reload
```

---

## `localhost:8501` refuses to connect

This means Streamlit is not currently running.

Start it with:

```bash
cd frontend
streamlit run app.py
```

---

## `localhost:8000` shows `{"detail":"Not Found"}`

This is normal.

The backend does not have a homepage. Open:

```text
http://localhost:8000/docs
```

instead.

---

## Database connection error

Check that:

1. MySQL is running.
2. The `hospital_capacity` database exists.
3. Your MySQL username and password are correct.
4. The `DB_*` environment variables are configured correctly.
5. The database schema has been imported.

---

## No hospital data appears

Run the seed script:

```bash
cd backend
python seed.py
```

Then refresh the Streamlit application.

---

# Stopping the Application

To stop either server, press:

```text
Ctrl + C
```

in its terminal.

---

# Important Security Note

Do not commit sensitive information such as:

* MySQL passwords
* API keys
* `.env` files containing secrets
* Production credentials

to GitHub.

For production deployment, use environment variables or the secret-management system provided by your hosting platform.

---

# Quick Start

After the database has been configured and seeded, start the application using two terminals.

### Terminal 1 — Backend

```bash
cd backend
uvicorn main:app --reload
```

### Terminal 2 — Frontend

```bash
cd frontend
streamlit run app.py
```

Then open:

**Application**

```text
http://localhost:8501
```

**API Documentation**

```text
http://localhost:8000/docs
```

---

## Project Status

This project is intended as a functional academic/demo system for managing hospital bed capacity, emergency requests, hospital matching, and reservations.
