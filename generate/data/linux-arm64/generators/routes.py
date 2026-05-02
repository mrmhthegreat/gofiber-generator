#!/usr/bin/env python3
"""
Complete Route Generator for Go Fiber Template System

Processes all YAML configs and generates unified route documentation.
"""

import yaml
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum

# Custom YAML dumper that disables anchors/aliases
class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


class RouteType(Enum):
    API = "api"
    WEB = "web"
    WEBSOCKET = "websocket"


@dataclass
class Route:
    name: str
    method: str
    path: str
    route_type: RouteType
    handler: str
    middleware: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    rate_limit: Dict[str, Any] = field(default_factory=dict)
    template: Optional[str] = None
    description: Optional[str] = None
    websocket_mode: Optional[str] = None  # unified/dedicated
    category: Optional[str] = None  # auth, rbac, chat, notification, or model name


class RouteGenerator:
    def __init__(self, config_path: str = "master_config.yaml"):
        self.config_path = Path(config_path)
        
        self.routes: List[Route] = []
        self.project_info = {}
        
    def load_yaml(self, path: Path) -> Dict[str, Any]:
        """Safely load YAML file"""
        if not path.exists():
            print(f"⚠️  Config not found: {path}")
            return {}
        try:
            with open(path, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"❌ Error loading {path}: {e}")
            return {}
    
    def extract_auth_routes(self, config: Dict) -> List[Route]:
        """Extract all authentication routes from auth config"""
        routes = []
        auth = config.get('authentication', {})
        
        # Project info
        self.project_info['module'] = config.get('project', {}).get('module', 'unknown')
        self.project_info['session_enabled'] = config.get('session', {}).get('enabled', False)
        self.project_info['rbac_enabled'] = config.get('rbac', {}).get('enabled', False)
        
        # === API ROUTES ===
        
        # Email/Password Auth
        ep = auth.get('email_password', {})
        # email_verification lives at authentication level (not inside email_password)
        ev = auth.get('email_verification', {})

        if ep.get('enabled', False):
            # Register
            routes.append(Route(
                name="RegisterUser",
                method="POST",
                path="/api/auth/register",
                route_type=RouteType.API,
                handler="RegisterUser",
                middleware=auth.get('register_middleware', []),
                rate_limit=auth.get('rate_limit', {}),
                category="auth"
            ))
            
            # Login
            routes.append(Route(
                name="LoginUser",
                method="POST",
                path="/api/auth/login",
                route_type=RouteType.API,
                handler="LoginUser",
                middleware=auth.get('middleware', []),
                rate_limit=auth.get('rate_limit', {}),
                category="auth"
            ))
            
            # Email Verification — defined at authentication level, not inside email_password
            if ev.get('enabled', False):
                routes.append(Route(
                    name="VerifyEmail",
                    method="POST",
                    path="/api/user/verify-email",
                    route_type=RouteType.API,
                    handler="VerifyEmail",
                    middleware=["auth"],
                    rate_limit=ev.get('rate_limit', auth.get('rate_limit', {})),
                    category="auth"
                ))
                routes.append(Route(
                    name="ResendVerification",
                    method="POST",
                    path="/api/user/resend-verification",
                    route_type=RouteType.API,
                    handler="ResendVerification",
                    middleware=ev.get('middleware', []),
                    rate_limit=ev.get('rate_limit', auth.get('rate_limit', {})),
                    category="auth"
                ))
            
            # Forgot Password
            fp = ep.get('forgot_password', {})
            if fp.get('enabled', False):
                routes.append(Route(
                    name="ForgotPassword",
                    method="POST",
                    path="/api/auth/forgot-password",
                    route_type=RouteType.API,
                    handler="ForgotPassword",
                    middleware=fp.get('middleware', []),
                    rate_limit=fp.get('rate_limit', auth.get('rate_limit', {})),
                    category="auth"
                ))
                routes.append(Route(
                    name="ResetPassword",
                    method="POST",
                    path="/api/auth/reset-password",
                    route_type=RouteType.API,
                    handler="ResetPassword",
                    middleware=[],
                    rate_limit=fp.get('rate_limit', auth.get('rate_limit', {})),
                    category="auth"
                ))
            
            # Change Password
            cp = ep.get('change_password', {})
            if cp.get('enabled', False):
                routes.append(Route(
                    name="ChangePassword",
                    method="POST",
                    path="/api/user/change-password",
                    route_type=RouteType.API,
                    handler="ChangePassword",
                    middleware=cp.get('middleware', ['auth']),
                    rate_limit=cp.get('rate_limit', auth.get('rate_limit', {})),
                    category="auth"
                ))
        
        # Refresh Token
        rt = auth.get('refresh_token', {})
        if rt.get('enabled', False):
            routes.append(Route(
                name="RefreshToken",
                method="POST",
                path="/api/auth/refresh-token",
                route_type=RouteType.API,
                handler="RefreshToken",
                middleware=[],
                rate_limit=auth.get('rate_limit', {})
            ))
        
        # Logout
        lo = auth.get('logout', {})
        if lo.get('enabled', False):
            routes.append(Route(
                name="Logout",
                method="POST",
                path="/api/auth/logout",
                route_type=RouteType.API,
                handler="Logout",
                middleware=["auth"],
                rate_limit=auth.get('rate_limit', {})
            ))
        
        # Social Auth API
        sa = auth.get('social_auth', {})
        for provider in ['google', 'facebook']:
            prov = sa.get(provider, {})
            if prov.get('enabled', False):
                api_cfg = prov.get('endpoints', {}).get('api', {})
                if api_cfg.get('enabled', True):
                    routes.append(Route(
                        name=f"{provider.capitalize()}Login",
                        method=api_cfg.get('method', 'POST'),
                        path=api_cfg.get('path', f'/api/auth/{provider}'),
                        route_type=RouteType.API,
                        handler=f"{provider.capitalize()}Login",
                        middleware=[]
                    ))
        
        # App Check Tokens
        for token in auth.get('app_check_tokens', []):
            routes.append(Route(
                name=f"Generate{token.get('name', '').replace('_', ' ').title().replace(' ', '')}",
                method="POST",
                path=f"/api/auth/{token.get('endpoint', '')}",
                route_type=RouteType.API,
                handler=token.get('name', ''),
                middleware=token.get('middleware', []),
                rate_limit=auth.get('rate_limit', {})
            ))
        
        # === WEB ROUTES ===
        
        web = auth.get('web_auth', {})
        if web.get('enabled', False):
            templates = web.get('templates', {})
            
            for key, ep_data in web.get('endpoints', {}).items():
                if not ep_data.get('enabled', False):
                    continue
                    
                path = ep_data.get('path', '')
                handler = ep_data.get('handler', '')
                rate_limit = ep_data.get('rate_limit', {})
                middleware = ep_data.get('middleware', [])
                
                # GET handler (page)
                if key in ['login', 'signup', 'forgot_password', 'verify_email']:
                    routes.append(Route(
                        name=f"{handler}",
                        method="GET",
                        path=path,
                        route_type=RouteType.WEB,
                        handler=handler,
                        middleware=middleware,
                        rate_limit=rate_limit,
                        template=templates.get(key)
                    ))
                    
                    # POST handler (action)
                    post_handler = f"Handle{handler.replace('Page', '').replace('Page', '')}"
                    if key == 'login': post_handler = 'HandleLogin'
                    elif key == 'signup': post_handler = 'HandleSignup'
                    elif key == 'forgot_password': post_handler = 'HandleForgotPassword'
                    elif key == 'reset_password': post_handler = 'HandleResetPassword'
                    elif key == 'verify_email': post_handler = 'HandleVerifyEmail'
                    
                    routes.append(Route(
                        name=post_handler,
                        method="POST",
                        path=path,
                        route_type=RouteType.WEB,
                        handler=post_handler,
                        middleware=middleware,
                        rate_limit=rate_limit,
                        template=None
                    ))
                else:
                    # Other endpoints (logout, etc)
                    routes.append(Route(
                        name=handler,
                        method="GET",
                        path=path,
                        route_type=RouteType.WEB,
                        handler=handler,
                        middleware=middleware,
                        rate_limit=rate_limit,
                        template=None
                    ))
            
            # Social Auth Web
            for provider in ['google', 'facebook']:
                prov = sa.get(provider, {})
                if prov.get('enabled', False):
                    web_p = prov.get('endpoints', {}).get('web', {})
                    if web_p.get('enabled', True):
                        routes.append(Route(
                            name=f"{provider.capitalize()}LoginWeb",
                            method="GET",
                            path=web_p.get('login_path', f'/auth/{provider}/login'),
                            route_type=RouteType.WEB,
                            handler=f"{provider.capitalize()}LoginWeb",
                            middleware=[]
                        ))
                        routes.append(Route(
                            name=f"{provider.capitalize()}CallbackWeb",
                            method="GET",
                            path=web_p.get('callback_path', f'/auth/{provider}/callback'),
                            route_type=RouteType.WEB,
                            handler=f"{provider.capitalize()}CallbackWeb",
                            middleware=[]
                        ))
        
        # === FCM ROUTES ===
        fcm = config.get('fcm', {})
        if fcm.get('enabled', False):
            # API Routes
            ctrl = fcm.get('controller', {})
            if ctrl.get('enabled', False):
                base_path = ctrl.get('base_path', '/api').rstrip('/')
                for key in ['SendFCM', 'SubscribeToTopic']:
                    ep = ctrl.get(key, {})
                    if ep.get('enabled', False):
                        routes.append(Route(
                            name=key,
                            method="POST",
                            path=f"{base_path}{ep.get('path', f'/{key.lower()}')}",
                            route_type=RouteType.API,
                            handler=f"FCMHandler.{key if key != 'SendFCM' else 'SendNotification'}",
                            middleware=ep.get('middleware', ctrl.get('middleware', [])),
                            category="fcm"
                        ))
                # Legacy / extra
                if not ctrl.get('SendFCM') and not ctrl.get('SubscribeToTopic'):
                     routes.append(Route(
                        name="FCMController",
                        method="POST",
                        path=f"{base_path}/fcm",
                        route_type=RouteType.API,
                        handler="FCMHandler",
                        category="fcm"
                    ))

            # Web Routes
            web_h = fcm.get('web_handler', {})
            if web_h.get('enabled', False):
                base_path = web_h.get('base_path', '/dashboard/notifications').rstrip('/')
                for key in ['GetNotificationPage', 'SendFCM', 'SubscribeToTopic']:
                    ep = web_h.get(key, {})
                    if ep.get('enabled', False):
                        method = "GET" if key == "GetNotificationPage" else "POST"
                        routes.append(Route(
                            name=key,
                            method=method,
                            path=f"{base_path}{ep.get('path', '/') if key == 'GetNotificationPage' else ep.get('path', f'/{key.lower()}')}",
                            route_type=RouteType.WEB,
                            handler=f"FCMHandler.{key if key != 'SendFCM' else 'SendNotification'}",
                            middleware=ep.get('middleware', web_h.get('middleware', [])),
                            permissions=ep.get('permissions', web_h.get('permissions', [])),
                            category="fcm"
                        ))

        # === IMAP/Email ROUTES ===
        imap = config.get('imap', {})
        if imap.get('enabled', False):
            # API Routes
            ctrl = imap.get('controller', {})
            if ctrl.get('enabled', False):
                base_path = ctrl.get('base_path', '/api').rstrip('/')
                for key in ['GetEmailsList', 'GetEmailDetail', 'SendEmail', 'MarkEmailRead', 'RefreshEmails']:
                    ep = ctrl.get(key, {})
                    if ep.get('enabled', False):
                        method = "POST" if key in ['SendEmail', 'RefreshEmails'] else ("PATCH" if key == 'MarkEmailRead' else "GET")
                        handler = "EmailHandler.ComposeEmail" if key == "SendEmail" else f"EmailHandler.{key}"
                        routes.append(Route(
                            name=key,
                            method=method,
                            path=f"{base_path}{ep.get('path', f'/{key.lower()}')}",
                            route_type=RouteType.API,
                            handler=handler,
                            middleware=ep.get('middleware', ctrl.get('middleware', [])),
                            category="imap"
                        ))

            # Web Routes
            web_h = imap.get('web_handler', {})
            if web_h.get('enabled', False):
                base_path = web_h.get('base_path', '/dashboard/emails').rstrip('/')
                for key in ['GetInboxPage', 'GetSentEmails', 'GetEmailsList', 'GetEmailDetail', 'SendEmail', 'MarkEmailRead', 'RefreshEmails']:
                    ep = web_h.get(key, {})
                    if ep.get('enabled', False):
                        method = "POST" if key in ['SendEmail', 'RefreshEmails'] else ("PATCH" if key == 'MarkEmailRead' else "GET")
                        handler = "EmailHandler.GetSentPage" if key == "GetSentEmails" else ("EmailHandler.ComposeEmail" if key == "SendEmail" else f"EmailHandler.{key}")
                        routes.append(Route(
                            name=key,
                            method=method,
                            path=f"{base_path}{ep.get('path', f'/{key.lower()}')}",
                            route_type=RouteType.WEB,
                            handler=handler,
                            middleware=ep.get('middleware', web_h.get('middleware', [])),
                            permissions=ep.get('permissions', web_h.get('permissions', [])),
                            category="imap"
                        ))

        # === RBAC ROUTES ===
        rbac = config.get('rbac', {})
        if rbac.get('enabled', False):
            # API Routes
            ctrl = rbac.get('controller', {})
            if ctrl.get('enabled', False):
                base_path = ctrl.get('base_path', '/api/rbac').rstrip('/')
                endpoints = [
                    ('ListRoles', 'GET', 'GetRoles'),
                    ('GetRole', 'GET', 'GetRolePermissions'),
                    ('CreateRole', 'POST', 'CreateRole'),
                    ('UpdateRole', 'PUT', 'UpdateRole'),
                    ('DeleteRole', 'DELETE', 'DeleteRole'),
                    ('ListPermissions', 'GET', 'GetPermissions'),
                    ('SyncPermissions', 'POST', 'SyncPermissions'), # Inferred
                    ('GetUserOverrides', 'GET', 'GetUserPermissionOverrides'),
                    ('SetUserOverride', 'POST', 'CreateUserPermissionOverride'),
                    ('SetUserOverride', 'PUT', 'UpdateUserPermissionOverrides'),
                    ('RemoveUserOverride', 'DELETE', 'DeleteUserPermissionOverride'),
                    ('BulkUpdateRolePermissions', 'PUT', 'UpdateRolePermissions'),
                    ('GetUserPermissions', 'GET', 'GetUserRolePermissions'),
                    ('InvalidateCache', 'POST', 'InvalidateUserCache'),
                    ('CheckPermission', 'GET', 'CheckPermission')
                ]
                
                for key, method, handler in endpoints:
                    ep = ctrl.get(key, {})
                    if ep.get('enabled', False):
                        routes.append(Route(
                            name=handler,
                            method=method,
                            path=f"{base_path}{ep.get('path', f'/{key.lower()}')}",
                            route_type=RouteType.API,
                            handler=f"RBACController.{handler}",
                            category="rbac"
                        ))
                
                # Special /me/permissions
                routes.append(Route(
                    name="GetMyPermissions",
                    method="GET",
                    path=f"{base_path}/me/permissions",
                    route_type=RouteType.API,
                    handler="RBACController.GetMyPermissions",
                    category="rbac"
                ))
                # Special /users/search
                routes.append(Route(
                    name="SearchUsers",
                    method="GET",
                    path=f"{base_path}/users/search",
                    route_type=RouteType.API,
                    handler="RBACController.SearchUsers",
                    category="rbac"
                ))

            # Web Routes
            web_h = rbac.get('web_handler', {})
            if web_h.get('enabled', False):
                base_path = web_h.get('base_path', '/dashboard/rbac').rstrip('/')
                
                if web_h.get('ManageRolesPage', {}).get('enabled', False):
                    ep = web_h.get('ManageRolesPage')
                    routes.append(Route(
                        name="ManageRolesPage",
                        method="GET",
                        path=f"{base_path}{ep.get('path', '/roles')}",
                        route_type=RouteType.WEB,
                        handler="RBACController.ShowRBACManagement",
                        permissions=ep.get('permissions', web_h.get('permissions', [])),
                        category="rbac"
                    ))
                
                if web_h.get('ManageOverridesPage', {}).get('enabled', False):
                    ep = web_h.get('ManageOverridesPage')
                    routes.append(Route(
                        name="ManageOverridesPage",
                        method="GET",
                        path=f"{base_path}{ep.get('path', '/overrides')}",
                        route_type=RouteType.WEB,
                        handler="RBACController.ShowRBACManagement",
                        permissions=ep.get('permissions', web_h.get('permissions', [])),
                        category="rbac"
                    ))
                    
        return routes
    
    def extract_chat_websocket_routes(self, config: Dict) -> List[Route]:
        """Extract chat, notification, and WebSocket routes"""
        routes = []
        
        # === CHAT API ROUTES ===
        # Extract chat API routes regardless of websocket status
        chat = config.get('chat', {})
        if chat.get('enabled', False):
            ctrl = chat.get('controller', {})
            if ctrl.get('enabled', False):
                base = ctrl.get('base_path', '/api/v1/chat')
                
                # Standard CRUD endpoints
                endpoints = ctrl.get('endpoints', {})
                
                if endpoints.get('list_conversations', {}).get('enabled', True):
                    routes.append(Route(
                        name="ListConversations",
                        method="GET",
                        path=f"{base}/conversations",
                        route_type=RouteType.API,
                        handler="ListConversations",
                        middleware=endpoints.get('list_conversations', {}).get('middleware', ['auth']),
                        description="List user conversations",
                        category="chat"
                    ))
                
                if endpoints.get('list_messages', {}).get('enabled', True):
                    routes.append(Route(
                        name="ListMessages",
                        method="GET",
                        path=f"{base}/conversations/:id/messages",
                        route_type=RouteType.API,
                        handler="ListMessages",
                        middleware=endpoints.get('list_messages', {}).get('middleware', ['auth']),
                        description="Get messages in conversation",
                        category="chat"
                    ))
                
                if endpoints.get('send_message', {}).get('enabled', True):
                    routes.append(Route(
                        name="SendMessage",
                        method="POST",
                        path=f"{base}/conversations/:id/messages",
                        route_type=RouteType.API,
                        handler="SendMessage",
                        middleware=endpoints.get('send_message', {}).get('middleware', ['auth']),
                        description="Send message to conversation",
                        category="chat"
                    ))
                
                if endpoints.get('mark_as_read', {}).get('enabled', True):
                    routes.append(Route(
                        name="MarkAsRead",
                        method="POST",
                        path=f"{base}/conversations/:id/read",
                        route_type=RouteType.API,
                        handler="MarkAsRead",
                        middleware=endpoints.get('mark_as_read', {}).get('middleware', ['auth']),
                        description="Mark conversation as read",
                        category="chat"
                    ))
            
            # Chat Web Handler
            web_h = chat.get('web_handler', {})
            if web_h.get('enabled', False):
                base = web_h.get('base_path', '/chat')
                
                # CRUD web endpoints
                crud = web_h.get('crud_settings', {})
                
                if crud.get('list_conversations', {}).get('enabled', True):
                    routes.append(Route(
                        name="ChatListConversations",
                        method="GET",
                        path=f"{base}/conversations",
                        route_type=RouteType.WEB,
                        handler="ChatListConversations",
                        middleware=web_h.get('middleware', ['auth']),
                        permissions=web_h.get('permissions', []),
                        template="views/chat/conversations.html",
                        category="chat"
                    ))
                
                if crud.get('list_messages', {}).get('enabled', True):
                    routes.append(Route(
                        name="ChatListMessages",
                        method="GET",
                        path=f"{base}/conversations/:id/messages",
                        route_type=RouteType.WEB,
                        handler="ChatListMessages",
                        middleware=web_h.get('middleware', ['auth']),
                        permissions=web_h.get('permissions', []),
                        template="views/chat/messages.html",
                        category="chat"
                    ))
                
                if crud.get('send_message', {}).get('enabled', True):
                    routes.append(Route(
                        name="ChatSendMessage",
                        method="POST",
                        path=f"{base}/send-message",
                        route_type=RouteType.WEB,
                        handler="ChatSendMessage",
                        middleware=web_h.get('middleware', ['auth']),
                        permissions=crud.get('send_message', {}).get('permissions', ['chat.send']),
                        category="chat"
                    ))
        
        # === WEBSOCKET ROUTES ===
        ws = config.get('websocket', {})
        if ws.get('enabled', False):
            ws_path = ws.get('path', '/ws')
            handler_type = ws.get('handler_type', 'unified')
            
            if handler_type == 'unified':
                routes.append(Route(
                    name="WebSocketUnified",
                    method="WS",
                    path=ws_path,
                    route_type=RouteType.WEBSOCKET,
                    handler="WebSocketHandler",
                    websocket_mode="unified",
                    description="Unified WebSocket endpoint",
                    category="websocket"
                ))
            else:
                # Dedicated mode - separate endpoints
                dedicated = ws.get('dedicated', {})
                
                # Chat WebSocket
                if config.get('chat', {}).get('enabled', False):
                    chat_path = dedicated.get('chat', {}).get('path', '/ws/chat')
                    routes.append(Route(
                        name="ChatWebSocket",
                        method="WS",
                        path=chat_path,
                        route_type=RouteType.WEBSOCKET,
                        handler="ChatWebSocketHandler",
                        websocket_mode="dedicated",
                        description="Chat-specific WebSocket",
                        category="chat"
                    ))
                
                # Support WebSocket
                if config.get('chat', {}).get('modes', {}).get('support', False):
                    support_path = dedicated.get('support', {}).get('path', '/ws/support')
                    routes.append(Route(
                        name="SupportWebSocket",
                        method="WS",
                        path=support_path,
                        route_type=RouteType.WEBSOCKET,
                        handler="SupportWebSocketHandler",
                        websocket_mode="dedicated",
                        description="Support chat WebSocket",
                        category="chat"
                    ))
                
                # User WebSocket
                if dedicated.get('user', {}).get('enabled', True):
                    user_path = dedicated.get('user', {}).get('path', '/ws/user')
                    routes.append(Route(
                        name="UserWebSocket",
                        method="WS",
                        path=user_path,
                        route_type=RouteType.WEBSOCKET,
                        handler="UserWebSocketHandler",
                        websocket_mode="dedicated",
                        description="User notifications WebSocket",
                        category="notification"
                    ))
                
                # Events WebSocket
                if dedicated.get('events', {}).get('enabled', True):
                    events_path = dedicated.get('events', {}).get('path', '/ws/events')
                    routes.append(Route(
                        name="EventsWebSocket",
                        method="WS",
                        path=events_path,
                        route_type=RouteType.WEBSOCKET,
                        handler="EventsWebSocketHandler",
                        websocket_mode="dedicated",
                        description="Events/updates WebSocket",
                        category="websocket"
                    ))
        
        # === NOTIFICATION API ROUTES ===
        notif = config.get('notifications', {})
        if notif.get('enabled', False):
            ctrl = notif.get('controller', {})
            if ctrl.get('enabled', False):
                base = ctrl.get('base_path', '/api/v1/notifications')
                middleware = ctrl.get('middleware', ['auth'])
                
                endpoints = ctrl.get('endpoints', {})
                
                if endpoints.get('list', {}).get('enabled', True):
                    routes.append(Route(
                        name="ListNotifications",
                        method="GET",
                        path=f"{base}/list",
                        route_type=RouteType.API,
                        handler="ListNotifications",
                        middleware=middleware,
                        description="List user notifications",
                        category="notification"
                    ))
                
                if endpoints.get('mark_as_read', {}).get('enabled', True):
                    routes.append(Route(
                        name="MarkNotificationRead",
                        method="POST",
                        path=f"{base}/:id/read",
                        route_type=RouteType.API,
                        handler="MarkNotificationRead",
                        middleware=middleware,
                        description="Mark single notification as read",
                        category="notification"
                    ))
                
                if endpoints.get('mark_all_as_read', {}).get('enabled', False):
                    routes.append(Route(
                        name="MarkAllNotificationsRead",
                        method="POST",
                        path=f"{base}/read-all",
                        route_type=RouteType.API,
                        handler="MarkAllNotificationsRead",
                        middleware=middleware,
                        description="Mark all notifications as read",
                        category="notification"
                    ))
                
                if endpoints.get('bulk_mark_read', {}).get('enabled', True):
                    routes.append(Route(
                        name="BulkMarkNotificationsRead",
                        method="POST",
                        path=f"{base}/bulk-read",
                        route_type=RouteType.API,
                        handler="BulkMarkNotificationsRead",
                        middleware=middleware,
                        description="Bulk mark notifications as read",
                        category="notification"
                    ))
                
                if endpoints.get('unread_count', {}).get('enabled', True):
                    routes.append(Route(
                        name="GetUnreadCount",
                        method="GET",
                        path=f"{base}/unread-count",
                        route_type=RouteType.API,
                        handler="GetUnreadCount",
                        middleware=middleware,
                        description="Get unread notification count",
                        category="notification"
                    ))
                
                if endpoints.get('delete', {}).get('enabled', True):
                    routes.append(Route(
                        name="DeleteNotification",
                        method="DELETE",
                        path=f"{base}/:id",
                        route_type=RouteType.API,
                        handler="DeleteNotification",
                        middleware=middleware,
                        description="Delete notification",
                        category="notification"
                    ))
                
                if endpoints.get('delete_all', {}).get('enabled', True):
                    routes.append(Route(
                        name="DeleteAllNotifications",
                        method="DELETE",
                        path=f"{base}/all",
                        route_type=RouteType.API,
                        handler="DeleteAllNotifications",
                        middleware=middleware,
                        description="Delete all notifications",
                        category="notification"
                    ))
        
        return routes
    
    def extract_model_routes(self, config: Dict) -> List[Route]:
        """Extract routes from repository/model config"""
        routes = []
        
        for model in config.get('models', []):
            model_name = model.get('name', 'Unknown')
            
            # API Controller routes
            ctrl = model.get('controller', {})
            if ctrl and ctrl.get('enabled', False):
                base = ctrl.get('base_path', f'/api/{model_name.lower()}s')
                tag = ctrl.get('tag', model_name)
                middleware = ctrl.get('middleware', [])
                rate_limit = ctrl.get('rate_limit', {})
                
                crud = ctrl.get('crud_settings', {})
                
                # Create
                if crud.get('create', {}).get('enabled', False):
                    routes.append(Route(
                        name=f"Create{model_name}",
                        method=crud['create'].get('method', 'POST'),
                        path=base,
                        route_type=RouteType.API,
                        handler=f"Create{model_name}",
                        middleware=crud['create'].get('middleware', middleware),
                        rate_limit=crud['create'].get('rate_limit', rate_limit),
                        description=f"Create new {model_name}",
                        category=model_name
                    ))
                
                # Get by ID
                if crud.get('get', {}).get('enabled', False):
                    routes.append(Route(
                        name=f"Get{model_name}ByID",
                        method="GET",
                        path=f"{base}/:id",
                        route_type=RouteType.API,
                        handler=f"Get{model_name}ByID",
                        middleware=crud['get'].get('middleware', middleware),
                        rate_limit=crud['get'].get('rate_limit', rate_limit),
                        description=f"Get {model_name} by ID",
                        category=model_name
                    ))
                
                # Update
                if crud.get('update', {}).get('enabled', False):
                    routes.append(Route(
                        name=f"Update{model_name}",
                        method=crud['update'].get('method', 'PATCH'),
                        path=f"{base}/:id",
                        route_type=RouteType.API,
                        handler=f"Update{model_name}",
                        middleware=crud['update'].get('middleware', middleware),
                        rate_limit=crud['update'].get('rate_limit', rate_limit),
                        description=f"Update {model_name}",
                        category=model_name
                    ))
                
                # Delete
                if crud.get('delete', {}).get('enabled', False):
                    routes.append(Route(
                        name=f"Delete{model_name}",
                        method="DELETE",
                        path=f"{base}/:id",
                        route_type=RouteType.API,
                        handler=f"Delete{model_name}",
                        middleware=crud['delete'].get('middleware', middleware),
                        rate_limit=crud['delete'].get('rate_limit', rate_limit),
                        description=f"Delete {model_name}",
                        category=model_name
                    ))
                
                # Batch Delete
                if crud.get('batch_delete', {}).get('enabled', False):
                    routes.append(Route(
                        name=f"BatchDelete{model_name}",
                        method="DELETE",
                        path=f"{base}/batch",
                        route_type=RouteType.API,
                        handler=f"BatchDelete{model_name}",
                        middleware=crud['batch_delete'].get('middleware', middleware),
                        rate_limit=crud['batch_delete'].get('rate_limit', rate_limit),
                        description=f"Batch delete {model_name}s",
                        category=model_name
                    ))
                
                # Custom getter endpoints
                for getter in model.get('custom_getters', []):
                    g_ctrl = getter.get('controller', {})
                    if not g_ctrl or not g_ctrl.get('enabled', False):
                        continue
                    
                    g_name = getter.get('name', 'UnknownGetter')
                    g_path = g_ctrl.get('path', f"{base}/{g_name.lower()}")
                    
                    routes.append(Route(
                        name=g_name,
                        method=g_ctrl.get('method', 'GET'),
                        path=g_path,
                        route_type=RouteType.API,
                        handler=g_name,
                        middleware=g_ctrl.get('middleware', middleware),
                        rate_limit=g_ctrl.get('rate_limit', rate_limit),
                        description=g_ctrl.get('description', f"Custom getter: {g_name}"),
                        category=model_name
                    ))
            
            # Web Handler routes
            web_h = model.get('web_handler', {})
            if web_h and web_h.get('enabled', False):
                base = web_h.get('base_path', f'/dashboard/{model_name.lower()}s')
                middleware = web_h.get('middleware', ['auth'])
                rate_limit = web_h.get('rate_limit', {})
                
                crud = web_h.get('crud_settings', {})
                
                # List/Index
                if crud.get('list', {}).get('enabled', False):
                    routes.append(Route(
                        name=f"List{model_name}",
                        method="GET",
                        path=base,
                        route_type=RouteType.WEB,
                        handler=f"List{model_name}",
                        middleware=crud['list'].get('middleware', middleware),
                        permissions=crud['list'].get('permissions', []),
                        rate_limit=crud['list'].get('rate_limit', rate_limit),
                        template=crud['list'].get('template', f'views/{model_name.lower()}/index.html'),
                        category=model_name
                    ))
                
                # Create Page
                if crud.get('create_page', {}).get('enabled', False):
                    routes.append(Route(
                        name=f"Create{model_name}Page",
                        method="GET",
                        path=f"{base}/new",
                        route_type=RouteType.WEB,
                        handler=f"Create{model_name}Page",
                        middleware=crud['create_page'].get('middleware', middleware),
                        permissions=crud['create_page'].get('permissions', []),
                        rate_limit=crud['create_page'].get('rate_limit', rate_limit),
                        template=crud['create_page'].get('template', f'views/{model_name.lower()}/create.html'),
                        category=model_name
                    ))
                
                # Create Action
                if crud.get('create', {}).get('enabled', False):
                    routes.append(Route(
                        name=f"Create{model_name}",
                        method="POST",
                        path=base,
                        route_type=RouteType.WEB,
                        handler=f"Create{model_name}",
                        middleware=crud['create'].get('middleware', middleware),
                        permissions=crud['create'].get('permissions', []),
                        rate_limit=crud['create'].get('rate_limit', rate_limit),
                        category=model_name
                    ))
                
                # Edit Page
                if crud.get('edit_page', {}).get('enabled', False):
                    routes.append(Route(
                        name=f"Edit{model_name}Page",
                        method="GET",
                        path=f"{base}/:id/edit",
                        route_type=RouteType.WEB,
                        handler=f"Edit{model_name}Page",
                        middleware=crud['edit_page'].get('middleware', middleware),
                        permissions=crud['edit_page'].get('permissions', []),
                        rate_limit=crud['edit_page'].get('rate_limit', rate_limit),
                        template=crud['edit_page'].get('template', f'views/{model_name.lower()}/edit.html'),
                        category=model_name
                    ))
                
                # Update Action
                if crud.get('update', {}).get('enabled', False):
                    routes.append(Route(
                        name=f"Update{model_name}",
                        method="POST",
                        path=f"{base}/:id",
                        route_type=RouteType.WEB,
                        handler=f"Update{model_name}",
                        middleware=crud['update'].get('middleware', middleware),
                        permissions=crud['update'].get('permissions', []),
                        rate_limit=crud['update'].get('rate_limit', rate_limit),
                        category=model_name
                    ))
                
                # Get/Show
                if crud.get('get', {}).get('enabled', False):
                    routes.append(Route(
                        name=f"Show{model_name}",
                        method="GET",
                        path=f"{base}/:id",
                        route_type=RouteType.WEB,
                        handler=f"Show{model_name}",
                        middleware=crud['get'].get('middleware', middleware),
                        permissions=crud['get'].get('permissions', []),
                        rate_limit=crud['get'].get('rate_limit', rate_limit),
                        template=crud['get'].get('template', f'views/{model_name.lower()}/show.html'),
                        category=model_name
                    ))
                
                # Delete
                if crud.get('delete', {}).get('enabled', False):
                    routes.append(Route(
                        name=f"Delete{model_name}",
                        method="DELETE",
                        path=f"{base}/:id",
                        route_type=RouteType.WEB,
                        handler=f"Delete{model_name}",
                        middleware=crud['delete'].get('middleware', middleware),
                        permissions=crud['delete'].get('permissions', []),
                        rate_limit=crud['delete'].get('rate_limit', rate_limit),
                        category=model_name
                    ))
                
                # Custom getter web handlers
                for getter in model.get('custom_getters', []):
                    g_web = getter.get('web_handler', {})
                    if not g_web or not g_web.get('enabled', False):
                        continue
                    
                    g_name = getter.get('name', 'UnknownGetter')
                    g_path = g_web.get('path', f"{base}/{g_name.lower()}")
                    
                    routes.append(Route(
                        name=g_name,
                        method="GET",
                        path=g_path,
                        route_type=RouteType.WEB,
                        handler=g_name,
                        middleware=g_web.get('middleware', middleware),
                        permissions=g_web.get('permissions', []),
                        rate_limit=g_web.get('rate_limit', rate_limit),
                        template=g_web.get('template', f'views/{model_name.lower()}/{g_name.lower()}.html'),
                        category=model_name
                    ))
        
        return routes
    
    def generate(self, output_file: str = "complete_routes.yaml"):
        """Generate complete route documentation"""
        print("=" * 80)
        print("COMPLETE ROUTE GENERATOR")
        print("=" * 80)
        
        # Load config
        print("\n📂 Loading configuration...")
        config = self.load_yaml(self.config_path)
        
        # Extract routes
        print("\n🔍 Extracting routes...")
        
        auth_routes = self.extract_auth_routes(config)
        print(f"  ✅ Auth/System routes: {len(auth_routes)}")
        
        chat_ws_routes = self.extract_chat_websocket_routes(config)
        print(f"  ✅ Chat/WebSocket routes: {len(chat_ws_routes)}")
        
        model_routes = self.extract_model_routes(config)
        print(f"  ✅ Model routes: {len(model_routes)}")
        
        self.routes = auth_routes + chat_ws_routes + model_routes
        
        # Build simplified output structure
        output = {
            'project': self.project_info.get('module', 'unknown'),
            'session_enabled': self.project_info.get('session_enabled', False),
            'rbac_enabled': self.project_info.get('rbac_enabled', False),
            'summary': {
                'total_routes': len(self.routes),
                'api_routes': len([r for r in self.routes if r.route_type == RouteType.API]),
                'web_routes': len([r for r in self.routes if r.route_type == RouteType.WEB]),
                'websocket_routes': len([r for r in self.routes if r.route_type == RouteType.WEBSOCKET]),
            },
            'api': {},
            'web': {},
            'websocket': []
        }
        
        # Group routes
        for route in self.routes:
            # Create copies of lists/dicts to avoid YAML anchors/aliases
            route_dict = {
                'name': route.name,
                'method': route.method,
                'path': route.path,
                'handler': route.handler,
                'middleware': list(route.middleware) if route.middleware else [],
                'permissions': list(route.permissions) if route.permissions else [],
                'rate_limit': dict(route.rate_limit) if route.rate_limit else {},
            }
            if route.template:
                route_dict['template'] = route.template
            if route.description:
                route_dict['description'] = route.description
            if route.websocket_mode:
                route_dict['websocket_mode'] = route.websocket_mode
            
            cat = route.category or 'other'
            
            if route.route_type == RouteType.API:
                if cat not in output['api']:
                    output['api'][cat] = []
                output['api'][cat].append(route_dict)
            elif route.route_type == RouteType.WEB:
                if cat not in output['web']:
                    output['web'][cat] = []
                output['web'][cat].append(route_dict)
            elif route.route_type == RouteType.WEBSOCKET:
                route_dict['category'] = cat
                output['websocket'].append(route_dict)
        
        # Write output
        print(f"\n💾 Writing to {output_file}...")
        with open(output_file, 'w') as f:
            yaml.dump(output, f, Dumper=NoAliasDumper, default_flow_style=False, sort_keys=False, indent=2, allow_unicode=True)
        
        print(f"\n" + "=" * 80)
        print("GENERATION COMPLETE")
        print("=" * 80)
        print(f"\n📊 Summary:")
        print(f"   Total routes: {output['summary']['total_routes']}")
        print(f"   API routes: {output['summary']['api_routes']}")
        print(f"   Web routes: {output['summary']['web_routes']}")
        print(f"   WebSocket routes: {output['summary']['websocket_routes']}")
        print(f"\n✅ Output: {output_file}")
        
        return output


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate complete route documentation')
    parser.add_argument('--config', default='master_config.yaml', help='Master configuration file')
    parser.add_argument('-o', '--output', default='complete_routes.yaml', help='Output file')
    
    args = parser.parse_args()
    
    generator = RouteGenerator(config_path=args.config)
    
    generator.generate(output_file=args.output)


if __name__ == '__main__':
    main()
