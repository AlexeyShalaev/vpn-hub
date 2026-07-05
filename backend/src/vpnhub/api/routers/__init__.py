"""Сборка всех роутеров API."""

from __future__ import annotations

from fastapi import APIRouter

from vpnhub.api.routers import admin, auth, events, health, member, owner

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(owner.router)
api_router.include_router(member.router)
api_router.include_router(admin.router)
api_router.include_router(events.router)
