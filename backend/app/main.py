from fastapi import FastAPI

from app.routes import admin, imports, manual, menu, next_meal, postmark, settings, today, users

app = FastAPI(title="thecube")
app.include_router(users.router)
app.include_router(imports.router)
app.include_router(today.router)
app.include_router(settings.router)
app.include_router(menu.router)
app.include_router(manual.router)
app.include_router(next_meal.router)
app.include_router(admin.router)
app.include_router(postmark.router)
