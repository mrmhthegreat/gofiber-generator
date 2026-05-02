import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import requests
import json
import os
import hmac
import hashlib
import base64
from datetime import datetime, timedelta
import logging
from typing import Optional, Dict, Any

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ApiClient:
    def __init__(self, base_url: str = "http://192.168.1.10:3000"):
        self.base_url = base_url
        self.session = requests.Session()
        
        # Authentication tokens
        self.access_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6Im1lcm9sYWRvYXBuaTFAZ21haWwuY29tIiwiZXhwIjoxNzczNDMxMjI1LCJpYXQiOjE3NzMzNDQ4MjUsImlzX3NlbGxlciI6dHJ1ZSwidXNlcl9pZCI6MTR9.aHzQ9u9uII2hMeyyG5dHo5aikJeNqIZCsAB8AsD4sp0"
        self.app_token = ""
        self.api_key = ""
        self.access_token_expiration = datetime.now()
        self.app_token_expiration = datetime.now()
        
        # Load from environment variables
        self.api_key = 'O+4qjUzUpySKNUh-x0e-ee=GgT3+SSeK'
        self.app_id = 'your_unique_flutter_app_id'
        self.sign_secret =  'sGyEIxoASbPUKLYWmkV-6A2vWxkyVphv'
        
        # Set default headers
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        
    def compute_signature(self, app_token: str, timestamp: str) -> str:
        """Compute lightweight request signature for app token validation"""
        if not self.sign_secret:
            raise ValueError("SIGN_SECRET not found in environment variables")
            
        data = app_token + timestamp
        key = self.sign_secret.encode('utf-8')
        message = data.encode('utf-8')
        signature = hmac.new(key, message, hashlib.sha256).digest()
        return base64.b64encode(signature).decode('utf-8')

    @property
    def is_authenticated_user(self) -> bool:
        """Check if user is logged in as authenticated user (has access token)"""
        return (self.access_token and 
                datetime.now() < self.access_token_expiration)

    @property
    def is_guest_user(self) -> bool:
        """Check if user is in guest mode (has app token but no access token)"""
        return (self.app_token and 
                datetime.now() < self.app_token_expiration and 
                not self.is_authenticated_user)

    @property
    def has_valid_app_token(self) -> bool:
        """Check if user has valid app token (required for all API calls)"""
        return (self.app_token and 
                datetime.now() < self.app_token_expiration)

    @property
    def auth_state(self) -> str:
        """Get current authentication state as string"""
        if self.is_authenticated_user:
            return "authenticated_user"
        elif self.is_guest_user:
            return "guest_user"
        elif self.has_valid_app_token:
            return "app_token_only"
        else:
            return "no_auth"

    def _prepare_headers(self, endpoint: str) -> Dict[str, str]:
        """Prepare authentication headers based on endpoint and auth state"""
        headers = {}
        
        # 1. USER AUTHENTICATION (Bearer Token)
        if self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
        
        # 2. GUEST API KEY (Only for guest-token endpoint)
        if '/auth/guest-token' in endpoint and self.api_key:
            headers['X-API-Key'] = self.api_key
        else:
            # 3. APP TOKEN + SIGNATURE (For all other requests)
            if self.app_token:
                # Check if app token is expired
                if datetime.now() >= self.app_token_expiration:
                    logger.warning("App token expired, refreshing...")
                    try:
                        self.get_guest_app_token()
                    except Exception as e:
                        logger.error(f"Failed to refresh app token: {e}")
                        raise Exception('App token expired and refresh failed')
                
                timestamp = datetime.utcnow().isoformat() + 'Z'
                signature = self.compute_signature(self.app_token, timestamp)
                
                # Add required headers for AppTokenMiddleware
                headers.update({
                    'X-API-Key': self.api_key,
                    'X-App-Token': self.app_token,
                    'X-Timestamp': timestamp,
                    'X-Request-Signature': signature
                })
        
        return headers
    
    def get_guest_app_token(self) -> Dict[str, Any]:
        """Get an app token for guest users using the API key"""
        if not self.api_key:
            raise ValueError("API key not found")
        
        if not self.app_id:
            raise ValueError("APP_ID not found in environment variables")
        
        logger.info("Getting guest app token...")
        
        try:
            # Use simple headers for guest token request
            headers = {
                'X-API-Key': self.api_key,
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            response = self.session.post(
                f"{self.base_url}/api/auth/guest-token",
                json={'app_id': self.app_id},
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                self.app_token = data['app_token']
                self.app_token_expiration = datetime.now() + timedelta(days=1)
                
                logger.info("Successfully obtained guest app token")
                return data
            else:
                raise Exception(f"Failed to get guest app token: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"Error getting guest app token: {e}")
            raise

    def make_request(self, method: str, endpoint: str, data: Optional[Dict] = None, 
                    files: Optional[Dict] = None, auth_level: str = "minimal") -> requests.Response:
        """Make API request with proper headers"""
        url = f"{self.base_url}{endpoint}"
        headers = self._prepare_headers(endpoint)
        
        # Remove Content-Type for file uploads
        if files:
            headers.pop('Content-Type', None)
        
        logger.info(f"Making {method.upper()} request to {endpoint}")
        logger.info(f"Auth headers: {list(headers.keys())}")
        logger.info(f"Auth state: {self.auth_state}")
            
        response = self.session.request(method, url, json=data, files=files, headers=headers)
        
        logger.info(f"Response status: {response.status_code}")
        if response.status_code >= 400:
            logger.error(f"Request failed: {response.text}")
        
        return response

class LemlyAPITester:
    def __init__(self, root):
        self.root = root
        self.root.title("Lemly API Testing Tool")
        self.root.geometry("1200x800")
        
        self.api_client = ApiClient()
        
        # API endpoints configuration
        self.endpoints = {
            "Authentication": {
                "Get Guest Token": ("POST", "/api/auth/guest-token", "guest", {
                    "app_id": "your_unique_flutter_app_id"
                }),
                "Register": ("POST", "/api/auth/register", "app_token", {
                    "username": "test_user",
                    "email": "test@example.com", 
                    "password": "password123",
                    "fullname": "Test User"
                }),
                "Login": ("POST", "/api/auth/login", "app_token", {
                    "email": "test@example.com",
                    "password": "password123"
                }),
                "Google Login": ("POST", "/api/auth/google", "app_token", {
                    "id_token": "google_id_token_here"
                }),
                "Facebook Login": ("POST", "/api/auth/facebook", "app_token", {
                    "id_token": "facebook_access_token_here"
                }),
                "Forgot Password": ("POST", "/api/auth/forgot-password", "app_token", {
                    "email": "test@example.com"
                }),
                "Reset Password": ("POST", "/api/auth/reset-password", "app_token", {
                    "email": "test@example.com",
                    "otp": "123456",
                    "new_password": "newpassword123"
                }),
                "Check Email": ("POST", "/api/auth/check-email", "app_token", {
                    "email": "test@example.com"
                })
            },
            "User Profile": {
                "Get Profile": ("GET", "/api/user/profile", "authenticated", {}),
                "Update Profile": ("PATCH", "/api/user/update", "authenticated", {
                    "fullname": "Updated Name",
                    "bio": "Updated bio"
                }),
                "Update Initial": ("PATCH", "/api/user/update_initial", "authenticated", {
                    "username": "new_username",
                    "address": "123 Main St"
                }),
                "Change Password": ("POST", "/api/user/change-password", "authenticated", {
                    "old_password": "oldpass123",
                    "new_password": "newpass123"
                }),
                "Verify Email": ("POST", "/api/user/verify-email", "authenticated", {
                    "email": "test@example.com",
                    "otp": "123456"
                }),
                "Resend Verify Email": ("GET", "/api/user/resend-verify-email", "authenticated", {}),
                "Check Username": ("GET", "/api/check-username?query=testuser", "app_token", {})
            },
            "Stripe" :{
               
               
                "On Board": ("POST", "/api/user/onboard", "authenticated", {}),
                "Kyc Status": ("GET", "/api/user/kyc-status", "authenticated", {}),
                "Stripe Dashboard": ("GET", "/api/user/stripe-dashboard", "authenticated", {}),
                "Bank Account": ("POST", "/api/user/bank-account", "authenticated", {"token":""}),
                "Balance": ("GET", "/api/user/balance", "authenticated", {}),
                "Transactions": ("GET", "/api/user/transactions", "authenticated", {}),
                "Payout": ("POST", "/api/user/payout", "authenticated", {
                    "currency":"usd",
                    "amount":100.0
                    }),
                "payments Detial": ("GET", "/api/user/payments/id/details", "authenticated", {}),
                "Payments Refund": ("POST", "/api/user/payments/id/refund", "authenticated", {}),
                "Confirm Payment": ("POST", "/api/confirm-payment", "", {
                    "payment_intent_id":""}
                                    ),
                "Place Order": ("POST", "/api/place-order", "", {
                    "products":[
                        {"product_id":1,
                        "size_id":1,
                        "quantity":1}
                        
                        ],
                    "address":{
                        "city":"",
                        "street":"",
                        "first_name":"",
                        "last_name":"",
                        "zipcode":"",
                        "email":"",
                        "phone":"",
                        },
                    "shipping_id":1,
                    "note":"",
                    "customer_hash":"",
                    "customer_id":2,
                    "save_address":False,
                    "user_id":"",
                    "basket_id":1

                    }),
                
            },
            "Products": {
                "Get Products": ("GET", "/api/user/live-products?offset=0&limit=10", "authenticated", {}),
                "Create Product": ("POST", "/api/user/create-live-products", "authenticated", {
                    "name": "Test Product",
                    "price": 29.99,
                    "size": "M"
                }),
                "Get Product by ID": ("GET", "/api/user/products/1", "authenticated", {}),
                "Update Product": ("PATCH", "/api/user/update-live-products/1", "authenticated", {
                    "name": "Updated Product",
                    "price": 39.99
                }),
                "Delete Products": ("DELETE", "/api/user/delete-live-products", "authenticated", {
                    "ids": ["1", "2"]
                }),
                "Duplicate Products": ("POST", "/api/user/dup-live-products", "authenticated", {
                    "ids": ["1", "2"]
                }),
                "Extract Info": ("POST", "/api/user/products/extract-info", "authenticated", {})
            },
            "Baskets": {
                "Get Baskets": ("GET", "/api/user/get-baskets?offset=0&limit=10", "authenticated", {}),
                "Create Basket": ("POST", "/api/user/create-basket", "authenticated", {
                    "name": "Summer Collection"
                }),
                "Delete Baskets": ("POST", "/api/user/baskets/delete", "authenticated", {
                    "ids": ["1", "2"]
                }),
                "Search Baskets": ("GET", "/api/user/baskets/search?name=summer", "authenticated", {}),
                "Get Basket Products": ("GET", "/api/user/baskets/1/products", "authenticated", {})
            },
            "Orders": {
                "Get Orders": ("GET", "/api/user/orders?offset=0&limit=10", "authenticated", {}),
                "Get Order by ID": ("GET", "/api/user/orders/1", "authenticated", {}),
                "Get Order Tracking": ("GET", "/api/user/orders/1/tracking", "authenticated", {})
            },
            "Shopping Trips": {
                "Get Shopping Trips": ("GET", "/api/user/shopping-trips?offset=0&limit=10", "authenticated", {}),
                "Get Trip Detail": ("GET", "/api/user/shopping-trips/1/detail", "authenticated", {}),
                "Update Trip": ("PATCH", "/api/user/shopping-trips/1", "authenticated", {})
            },
            "Wallet & Payments": {
                "Get Wallet": ("GET", "/api/user/my-wallet", "authenticated", {}),
                "Create Payout Method": ("POST", "/api/user/create-payout-method", "authenticated", {
                    "type": "bank",
                    "bank_name": "Example Bank",
                    "account_title": "John Doe",
                    "iban": "DE89370400440532013000",
                    "account_no": "1234567890",
                    "holder_name": "John Doe"
                }),
                "Update Payout Method": ("PATCH", "/api/user/update-payout-method", "authenticated", {
                    "bank_name": "Updated Bank"
                })
            },
            "Withdrawal Requests": {
                "Get Withdrawal Requests": ("GET", "/api/user/withdrawal-requests?offset=0&limit=10", "authenticated", {}),
                "Create Withdrawal Request": ("POST", "/api/user/withdrawal-requests", "authenticated", {
                    "withdraw_method_id": 1,
                    "order_ids": [1, 2],
                    "note": "Monthly withdrawal"
                }),
                "Get Request by ID": ("GET", "/api/user/withdrawal-requests/1", "authenticated", {}),
                "Delete Request": ("DELETE", "/api/user/withdrawal-requests/1", "authenticated", {})
            },
           
            "Activities": {
                "Get Activities": ("GET", "/api/user/activities?offset=0&limit=10", "authenticated", {}),
                "Get Recent Activities": ("GET", "/api/user/activities/recent?hours=24&limit=10", "authenticated", {})
            }
        }
        
        self.setup_ui()
        # AUTOMATICALLY GET GUEST TOKEN ON STARTUP
        self.root.after(500, self.auto_initialize_guest_token)
        
    def setup_ui(self):
        # Main container
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Left panel for endpoint selection
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        # Right panel for request/response
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Authentication section
        auth_frame = ttk.LabelFrame(left_frame, text="Authentication", padding=10)
        auth_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(auth_frame, text="API Key:").pack(anchor=tk.W)
        self.api_key_entry = ttk.Entry(auth_frame, width=30)
        self.api_key_entry.insert(0, self.api_client.api_key)
        self.api_key_entry.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(auth_frame, text="App ID:").pack(anchor=tk.W)
        self.app_id_entry = ttk.Entry(auth_frame, width=30)
        self.app_id_entry.insert(0, self.api_client.app_id)
        self.app_id_entry.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(auth_frame, text="Sign Secret:").pack(anchor=tk.W)
        self.sign_secret_entry = ttk.Entry(auth_frame, width=30, show="*")
        self.sign_secret_entry.insert(0, self.api_client.sign_secret)
        self.sign_secret_entry.pack(fill=tk.X, pady=(0, 5))
        
        # Buttons frame
        buttons_frame = ttk.Frame(auth_frame)
        buttons_frame.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Button(buttons_frame, text="Get Guest App Token", 
                  command=self.get_guest_token).pack(fill=tk.X, pady=(0, 2))
        ttk.Button(buttons_frame, text="Update Config", 
                  command=self.update_config).pack(fill=tk.X, pady=(0, 5))
        
        # Token display (read-only)
        ttk.Label(auth_frame, text="App Token:").pack(anchor=tk.W)
        self.app_token_entry = ttk.Entry(auth_frame, width=30, state="readonly")
        self.app_token_entry.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(auth_frame, text="Access Token:").pack(anchor=tk.W)
        self.access_token_entry = ttk.Entry(auth_frame, width=30, state="readonly")
        self.access_token_entry.pack(fill=tk.X, pady=(0, 5))
        
        # Auth status
        self.auth_status_label = ttk.Label(auth_frame, text="Auth Status: Initializing...", 
                                          foreground="orange")
        self.auth_status_label.pack(anchor=tk.W, pady=(5, 0))
        
        # Endpoints tree
        endpoints_frame = ttk.LabelFrame(left_frame, text="Endpoints", padding=10)
        endpoints_frame.pack(fill=tk.BOTH, expand=True)
        
        self.tree = ttk.Treeview(endpoints_frame)
        self.tree.pack(fill=tk.BOTH, expand=True)
        
        # Populate tree
        for category, endpoints in self.endpoints.items():
            category_id = self.tree.insert("", "end", text=category, values=("", "", "", ""))
            for endpoint_name, (method, url, auth, data) in endpoints.items():
                self.tree.insert(category_id, "end", text=endpoint_name, 
                               values=(method, url, auth, json.dumps(data)))
        
        self.tree.bind("<<TreeviewSelect>>", self.on_endpoint_select)
        
        # Request section
        request_frame = ttk.LabelFrame(right_frame, text="Request", padding=10)
        request_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Method and URL
        method_frame = ttk.Frame(request_frame)
        method_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(method_frame, text="Method:").pack(side=tk.LEFT)
        self.method_var = tk.StringVar()
        method_combo = ttk.Combobox(method_frame, textvariable=self.method_var, 
                                   values=["GET", "POST", "PATCH", "DELETE"], width=10)
        method_combo.pack(side=tk.LEFT, padx=(5, 10))
        
        ttk.Label(method_frame, text="URL:").pack(side=tk.LEFT)
        self.url_entry = ttk.Entry(method_frame)
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        # Auth level
        auth_frame_req = ttk.Frame(request_frame)
        auth_frame_req.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(auth_frame_req, text="Auth Level:").pack(side=tk.LEFT)
        self.auth_var = tk.StringVar()
        auth_combo = ttk.Combobox(auth_frame_req, textvariable=self.auth_var, 
                                 values=["guest", "app_token", "authenticated"], width=15)
        auth_combo.pack(side=tk.LEFT, padx=(5, 0))
        
        # Request body
        ttk.Label(request_frame, text="Request Body (JSON):").pack(anchor=tk.W)
        self.request_text = scrolledtext.ScrolledText(request_frame, height=8)
        self.request_text.pack(fill=tk.BOTH, expand=True, pady=(5, 10))
        
        # File upload section
        file_frame = ttk.Frame(request_frame)
        file_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(file_frame, text="File Upload:").pack(side=tk.LEFT)
        self.file_path_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.file_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 5))
        ttk.Button(file_frame, text="Browse", command=self.browse_file).pack(side=tk.LEFT)
        
        # Send button
        ttk.Button(request_frame, text="Send Request", command=self.send_request).pack(fill=tk.X)
        
        # Response section
        response_frame = ttk.LabelFrame(right_frame, text="Response", padding=10)
        response_frame.pack(fill=tk.BOTH, expand=True)
        
        self.response_text = scrolledtext.ScrolledText(response_frame)
        self.response_text.pack(fill=tk.BOTH, expand=True)

    def auto_initialize_guest_token(self):
        """AUTOMATICALLY GET GUEST APP TOKEN ON STARTUP"""
        try:
            logger.info("🚀 AUTO-INITIALIZING GUEST APP TOKEN ON STARTUP...")
            
            # Show loading status
            self.auth_status_label.config(text="Auth Status: Getting guest token...", foreground="orange")
            self.root.update()
            
            # Only get guest token if we don't already have a valid one
            if not self.api_client.has_valid_app_token:
                # Get guest app token automatically
                response = self.api_client.get_guest_app_token()
                
                # Update UI with the new app token
                self.app_token_entry.config(state="normal")
                self.app_token_entry.delete(0, tk.END)
                self.app_token_entry.insert(0, self.api_client.app_token)
                self.app_token_entry.config(state="readonly")
                
                logger.info(f"✅ GUEST APP TOKEN ACQUIRED AUTOMATICALLY: {self.api_client.app_token[:20]}...")
                
            # Update auth status
            self.update_auth_status()
                
        except Exception as e:
            logger.error(f"❌ FAILED TO AUTO-INITIALIZE GUEST TOKEN: {e}")
            self.auth_status_label.config(text="Auth Status: Failed to get guest token", foreground="red")
            
            # Show error message to user (non-blocking)
            self.root.after(100, lambda: messagebox.showwarning(
                "Auto-Initialization Failed", 
                f"Failed to automatically get guest token on startup:\n\n{str(e)}\n\nYou can manually get it by clicking 'Get Guest App Token' button."))

    def update_config(self):
        """Update API client configuration from UI"""
        self.api_client.api_key = self.api_key_entry.get()
        self.api_client.app_id = self.app_id_entry.get() 
        self.api_client.sign_secret = self.sign_secret_entry.get()
        self.update_auth_status()
        messagebox.showinfo("Success", "Configuration updated!")
        
    def get_guest_token(self):
        """Manually get guest app token using API key"""
        try:
            # Update client with current UI values first
            self.api_client.api_key = self.api_key_entry.get()
            self.api_client.app_id = self.app_id_entry.get()
            self.api_client.sign_secret = self.sign_secret_entry.get()
            
            # Show loading status
            self.auth_status_label.config(text="Auth Status: Getting guest token...", foreground="orange")
            self.root.update()
            
            # Get guest app token
            response = self.api_client.get_guest_app_token()
            
            # Update UI with tokens
            self.app_token_entry.config(state="normal")
            self.app_token_entry.delete(0, tk.END)
            self.app_token_entry.insert(0, self.api_client.app_token)
            self.app_token_entry.config(state="readonly")
            
            self.update_auth_status()
            
            messagebox.showinfo("Success", f"Guest app token acquired manually!\nToken: {self.api_client.app_token[:20]}...")
            
        except Exception as e:
            self.update_auth_status()
            messagebox.showerror("Error", f"Failed to get guest token: {str(e)}")
            logger.error(f"Manual guest token error: {e}")
    
    def update_auth_status(self):
        """Update authentication status display"""
        status = self.api_client.auth_state
        status_text = {
            "authenticated_user": ("Authenticated User", "green"),
            "guest_user": ("Guest User", "blue"),
            "app_token_only": ("App Token Only", "orange"),
            "no_auth": ("Not Authenticated", "red")
        }
        
        text, color = status_text.get(status, ("Unknown", "gray"))
        self.auth_status_label.config(text=f"Auth Status: {text}", foreground=color)
        
    def on_endpoint_select(self, event):
        """Handle endpoint selection from tree"""
        selection = self.tree.selection()
        if selection:
            item = self.tree.item(selection[0])
            values = item["values"]
            if len(values) == 4 and values[0]:  # Has method
                method, url, auth, data = values
                self.method_var.set(method)
                self.url_entry.delete(0, tk.END)
                self.url_entry.insert(0, url)
                self.auth_var.set(auth)
                
                # Pretty print JSON data
                try:
                    if data:
                        parsed_data = json.loads(data)
                        formatted_data = json.dumps(parsed_data, indent=2)
                        self.request_text.delete(1.0, tk.END)
                        self.request_text.insert(1.0, formatted_data)
                except:
                    self.request_text.delete(1.0, tk.END)
                    self.request_text.insert(1.0, data)
                    
    def browse_file(self):
        """Browse for file upload"""
        filename = filedialog.askopenfilename()
        if filename:
            self.file_path_var.set(filename)
            
    def send_request(self):
        """Send API request"""
        try:
            method = self.method_var.get()
            url = self.url_entry.get()
            auth_level = self.auth_var.get()
            
            # Update client configuration from UI
            self.api_client.api_key = self.api_key_entry.get()
            self.api_client.app_id = self.app_id_entry.get()
            self.api_client.sign_secret = self.sign_secret_entry.get()
            
            # Parse request body
            request_body = self.request_text.get(1.0, tk.END).strip()
            data = None
            if request_body:
                try:
                    data = json.loads(request_body)
                except json.JSONDecodeError as e:
                    messagebox.showerror("Error", f"Invalid JSON: {e}")
                    return
            
            # Handle file upload
            files = None
            file_path = self.file_path_var.get()
            if file_path and os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    files = {'image': f}
                    response = self.api_client.make_request(method, url, data, files, auth_level)
            else:
                response = self.api_client.make_request(method, url, data, None, auth_level)
            
            # Display response
            response_data = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body": response.text
            }
            
            # Try to parse JSON response
            try:
                response_json = response.json()
                response_data["body"] = response_json
            except:
                pass  # Keep as text
            
            formatted_response = json.dumps(response_data, indent=2, ensure_ascii=False)
            self.response_text.delete(1.0, tk.END)
            self.response_text.insert(1.0, formatted_response)
            
            # Update tokens if received in response
            self.update_tokens_from_response(response_data.get("body", {}))
            
        except Exception as e:
            
           
            try:
                response_data = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body": response.text
                }
                response_json = response.json()
                response_data["body"] = response_json
                self.update_tokens_from_response(response_data.get("body", {}))
                
            except:
                pass  # Keep as text
            
            
            messagebox.showerror("Error", f"Request failed: {str(e)}")
            self.response_text.delete(1.0, tk.END)
            self.response_text.insert(1.0, f"Error: {str(e)}")
    
    def update_tokens_from_response(self, response_body):
        """Update tokens from API response"""
        try:
            if isinstance(response_body, dict):
                # Update app token if present
                if "app_token" in response_body:
                    self.api_client.app_token = response_body["app_token"]
                    self.api_client.app_token_expiration = datetime.now() + timedelta(days=1)
                    
                    self.app_token_entry.config(state="normal")
                    self.app_token_entry.delete(0, tk.END)
                    self.app_token_entry.insert(0, self.api_client.app_token)
                    self.app_token_entry.config(state="readonly")
                
                # Update access token if present (from login)
                if "access_token" in response_body:
                    self.api_client.access_token = response_body["access_token"]
                    self.api_client.access_token_expiration = datetime.now() + timedelta(days=1)
                    
                    self.access_token_entry.config(state="normal")
                    self.access_token_entry.delete(0, tk.END)
                    self.access_token_entry.insert(0, self.api_client.access_token)
                    self.access_token_entry.config(state="readonly")
                if "token" in response_body:
                    self.api_client.access_token = response_body["token"]
                    self.api_client.access_token_expiration = datetime.now() + timedelta(days=1)
                    
                    self.access_token_entry.config(state="normal")
                    self.access_token_entry.delete(0, tk.END)
                    self.access_token_entry.insert(0, self.api_client.access_token)
                    self.access_token_entry.config(state="readonly")
                
                # Update auth status
                self.update_auth_status()
                
        except Exception as e:
            logger.error(f"Error updating tokens from response: {e}")

if __name__ == "__main__":
    # Set up environment variables for testing
    if not os.getenv('GUEST_API_KEY'):
        os.environ['GUEST_API_KEY'] = 'your_unique_flutter_app_id'
    if not os.getenv('APP_ID'):
        os.environ['APP_ID'] = 'your_unique_flutter_app_id'
    if not os.getenv('SIGN_SECRET'):
        os.environ['SIGN_SECRET'] = 'your_sign_secret_key_32_chars_long'
    
    root = tk.Tk()
    app = LemlyAPITester(root)
    root.mainloop()
