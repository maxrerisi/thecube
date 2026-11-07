from fastapi import FastAPI

from app.routes import admin, imports, settings, today, users

app = FastAPI(title="thecube")
app.include_router(users.router)
app.include_router(imports.router)
app.include_router(today.router)
app.include_router(settings.router)
app.include_router(admin.router)
