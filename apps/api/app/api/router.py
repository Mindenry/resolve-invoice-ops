"""Versioned API router aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.ai_evaluation.router import router as evaluation_router
from app.modules.analytics.router import router as analytics_router
from app.modules.approvals.router import router as approvals_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.cases.router import router as cases_router
from app.modules.documents.router import router as documents_router
from app.modules.exceptions.router import router as exceptions_router
from app.modules.integrations.router import router as integrations_router
from app.modules.investigation.router import router as investigation_router
from app.modules.invoices.router import router as invoices_router
from app.modules.notifications.router import router as notifications_router
from app.modules.organizations.router import router as organizations_router
from app.modules.purchase_orders.router import router as purchase_orders_router
from app.modules.resolutions.router import router as resolutions_router
from app.modules.saved_filters.router import router as saved_filters_router
from app.modules.users.router import router as users_router
from app.modules.vendors.router import router as vendors_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(organizations_router)
api_router.include_router(vendors_router)
api_router.include_router(purchase_orders_router)
api_router.include_router(invoices_router)
api_router.include_router(exceptions_router)
api_router.include_router(cases_router)
api_router.include_router(documents_router)
api_router.include_router(investigation_router)
api_router.include_router(resolutions_router)
api_router.include_router(approvals_router)
api_router.include_router(integrations_router)
api_router.include_router(notifications_router)
api_router.include_router(saved_filters_router)
api_router.include_router(analytics_router)
api_router.include_router(evaluation_router)
api_router.include_router(audit_router)
