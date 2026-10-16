# Real-Time Collaborative Task Board

A real-time collaborative task management backend built with **Python, FastAPI, PostgreSQL, Redis, WebSockets, and JWT authentication**.

The project demonstrates how to build and deploy an asynchronous backend API with authentication, authorization, database persistence, business rules, and real-time communication.

---

## 🚀 Live Deployment

**Backend:** Deployed on Render

**API Documentation:**  
`https://YOUR-RENDER-URL.onrender.com/docs`

> Replace `YOUR-RENDER-URL` with your actual Render Web Service URL.

---

## 📌 Project Overview

The Real-Time Collaborative Task Board is a backend application designed for teams to create, manage, and collaborate on tasks.

Users can:

- Register an account
- Log in securely
- Receive JWT authentication tokens
- Access protected endpoints
- Create tasks
- View tasks
- Update tasks
- Delete tasks
- Update task status
- Collaborate through real-time WebSocket communication

The application uses **PostgreSQL** for persistent data storage and **Redis Pub/Sub** as part of the real-time communication architecture.

---

## 🛠️ Tech Stack

### Backend

- Python
- FastAPI
- Uvicorn
- SQLAlchemy
- Psycopg

### Database

- PostgreSQL
- Redis

### Authentication & Security

- JWT
- PyJWT
- pwdlib
- Argon2 password hashing

### Real-Time Communication

- WebSockets
- Redis Pub/Sub

### Validation

- Pydantic

### Testing

- Pytest
- HTTPX

### Development & Deployment

- Git
- GitHub
- Docker
- Render
- VS Code

---

## 🏗️ Architecture

```text
                    ┌──────────────────┐
                    │     Client       │
                    │ Browser / API    │
                    └────────┬─────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │   FastAPI Backend   │
                  │      Render         │
                  └──────┬──────┬───────┘
                         │      │
             ┌───────────┘      └────────────┐
             ▼                               ▼
    ┌─────────────────┐             ┌─────────────────┐
    │   PostgreSQL    │             │      Redis      │
    │ Persistent Data │             │   Pub / Sub     │
    └─────────────────┘             └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │   WebSockets    │
                                    │ Real-Time Sync  │
                                    └─────────────────┘
