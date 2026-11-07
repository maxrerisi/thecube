from fastapi import FastAPI

from app.routes import admin, imports, users

app = FastAPI(title="thecube")
app.include_router(users.router)
app.include_router(imports.router)
app.include_router(admin.router)
