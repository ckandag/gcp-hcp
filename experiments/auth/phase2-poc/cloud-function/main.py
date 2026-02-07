"""
Google Cloud Function for token exchange.

This function exchanges a Google identity token (from gcloud) for an
Identity Platform token with custom claims containing IAM role mappings.

Endpoints:
  /exchange - Exchange gcloud token for IDP token with IAM roles
  /health   - Health check

Environment Variables:
  PROJECT_ID              - GCP Project ID
  IDP_API_KEY             - Identity Platform API Key
  REQUIRE_PROJECT_ACCESS  - Require IAM role on project (default: true)
"""

import functions_framework
from flask import request, jsonify
import urllib.request
import json
import base64
import os
import logging

logger = logging.getLogger(__name__)


# Configuration from environment variables (required)
PROJECT_ID = os.environ.get("PROJECT_ID")
if not PROJECT_ID:
    raise ValueError("PROJECT_ID environment variable is required")

IDP_API_KEY = os.environ.get("IDP_API_KEY")
if not IDP_API_KEY:
    raise ValueError("IDP_API_KEY environment variable is required")
REQUIRE_PROJECT_ACCESS = os.environ.get("REQUIRE_PROJECT_ACCESS", "true").lower() == "true"


# IAM Role to Kubernetes Group mapping
IAM_ROLE_MAPPING = {
    "roles/container.clusterAdmin": "cluster-admin",
    "roles/container.admin": "cluster-admin",
    "roles/owner": "cluster-admin",
    "roles/editor": "cluster-admin",
    "roles/container.clusterViewer": "cluster-viewer",
    "roles/container.viewer": "cluster-viewer",
    "roles/viewer": "cluster-viewer",
}


def get_service_account_token():
    """Get access token for the Cloud Function's service account."""
    import google.auth
    from google.auth.transport.requests import Request
    
    credentials, _ = google.auth.default()
    credentials.refresh(Request())
    return credentials.token


def get_user_iam_roles(email, project_id):
    """
    Get all IAM roles for a user on a project.
    
    Returns a list of roles the user has (directly or via domain/group).
    """
    try:
        access_token = get_service_account_token()
        
        # Get the IAM policy
        policy_url = f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}:getIamPolicy"
        
        req = urllib.request.Request(
            policy_url,
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}"
            },
            method="POST"
        )
        
        with urllib.request.urlopen(req) as response:
            policy = json.loads(response.read().decode())
        
        user_roles = []
        domain = email.split("@")[-1] if "@" in email else None
        
        for binding in policy.get("bindings", []):
            role = binding.get("role", "")
            members = binding.get("members", [])
            
            # Check if user is directly in the binding
            if f"user:{email}" in members:
                user_roles.append(role)
            # Check domain-wide access
            elif domain and f"domain:{domain}" in members:
                user_roles.append(role)
            # Check allUsers/allAuthenticatedUsers
            elif "allAuthenticatedUsers" in members:
                user_roles.append(role)
        
        return user_roles, None

    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        logger.error("IAM policy lookup failed (HTTP %d): %s", e.code, error_body)
        return [], "IAM lookup failed due to an internal error"
    except Exception as e:
        logger.exception("IAM policy lookup error")
        return [], "IAM lookup encountered an unexpected error"


def map_iam_roles_to_groups(iam_roles):
    """
    Map GCP IAM roles to Kubernetes groups.
    
    Returns a list of Kubernetes group names.
    """
    groups = set()
    
    for role in iam_roles:
        if role in IAM_ROLE_MAPPING:
            groups.add(IAM_ROLE_MAPPING[role])
    
    # If user has any role but no specific mapping, give them viewer access
    if iam_roles and not groups:
        groups.add("cluster-viewer")
    
    return list(groups)


def set_custom_claims(user_id, claims, project_id):
    """
    Set custom claims on a user's Identity Platform account.
    
    Uses the Identity Toolkit REST API to update user claims.
    These claims will appear in future tokens.
    """
    try:
        access_token = get_service_account_token()
        
        # Update user with custom claims
        update_url = f"https://identitytoolkit.googleapis.com/v1/projects/{project_id}/accounts:update"
        
        update_data = json.dumps({
            "localId": user_id,
            "customAttributes": json.dumps(claims)
        }).encode()
        
        req = urllib.request.Request(
            update_url,
            data=update_data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}"
            }
        )
        
        with urllib.request.urlopen(req) as response:
            return True, json.loads(response.read().decode())

    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        logger.error("Set custom claims failed (HTTP %d): %s", e.code, error_body)
        return False, "Set claims failed due to an internal error"
    except Exception as e:
        logger.exception("Set custom claims error")
        return False, "Set claims encountered an unexpected error"


def decode_jwt_claims(token):
    """Decode JWT claims without verification."""
    try:
        payload = token.split(".")[1]
        # Add padding if needed
        payload += "=" * (4 - len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {"error": "Could not decode token"}


@functions_framework.http
def oauth_handler(request):
    """Main entry point for the Cloud Function."""
    path = request.path

    if path.endswith("/exchange"):
        return handle_token_exchange(request)
    elif path.endswith("/health"):
        return jsonify({"status": "ok", "project": PROJECT_ID})
    else:
        # Default: show usage info
        return show_usage(request)


def handle_token_exchange(request):
    """
    Exchange a Google ID token for an Identity Platform token.
    
    This endpoint is designed for CLI usage - no browser required.
    The CLI calls this with a gcloud identity token and gets back an IDP token.
    
    Usage:
        curl -X POST -H "Content-Type: application/json" \
             -H "Authorization: Bearer <gcloud-token>" \
             -d '{"google_token": "<token>"}' \
             https://.../exchange
    
    Or pass token in Authorization header (will be extracted automatically).
    """
    # Get the Google ID token from request
    google_id_token = None
    
    # Try to get from JSON body
    if request.is_json:
        data = request.get_json()
        google_id_token = data.get("google_token")
    
    # Try to get from Authorization header
    if not google_id_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            google_id_token = auth_header[7:]
    
    if not google_id_token:
        return jsonify({
            "error": "No token provided",
            "usage": "POST with {'google_token': '<token>'} or Authorization: Bearer <token>"
        }), 400
    
    # Decode Google token to get claims
    google_claims = decode_jwt_claims(google_id_token)
    if "error" in google_claims:
        return jsonify({"error": "Invalid Google token", "details": google_claims}), 400
    
    # Get user email from token
    user_email = google_claims.get("email")
    if not user_email:
        return jsonify({"error": "No email in token"}), 400
    
    # Get user's IAM roles on the project
    iam_roles, iam_error = get_user_iam_roles(user_email, PROJECT_ID)
    
    # Check if user has access to the project
    if REQUIRE_PROJECT_ACCESS:
        if iam_error:
            logger.error("Access check failed for user %s: %s", user_email, iam_error)
            return jsonify({
                "error": "Access check failed",
                "message": f"Could not verify access for {user_email}"
            }), 500
        
        if not iam_roles:
            return jsonify({
                "error": "Access denied",
                "message": f"User {user_email} does not have any IAM role on project {PROJECT_ID}",
            }), 403
    
    # Map IAM roles to Kubernetes groups
    k8s_groups = map_iam_roles_to_groups(iam_roles)
    
    # Check if IDP_API_KEY is configured
    if not IDP_API_KEY:
        logger.error("IDP_API_KEY environment variable not configured")
        return jsonify({
            "error": "Identity Platform not configured",
            "message": "Server configuration error. Contact administrator."
        }), 500
    
    # Exchange with Identity Platform
    # Use oidc.gcloud provider which accepts gcloud SDK tokens
    try:
        idp_data = json.dumps({
            "postBody": f"id_token={google_id_token}&providerId=oidc.gcloud",
            "requestUri": "http://localhost",
            "returnIdpCredential": True,
            "returnSecureToken": True
        }).encode()

        req = urllib.request.Request(
            f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp?key={IDP_API_KEY}",
            data=idp_data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as response:
            idp_response = json.loads(response.read().decode())

        idp_token = idp_response.get("idToken")
        user_id = idp_response.get("localId")

        if not idp_token:
            logger.error("No ID token in IDP response: %s", json.dumps(idp_response))
            return jsonify({
                "error": "Identity Platform exchange failed",
                "message": "No ID token received from Identity Platform"
            }), 500
        
        # Set custom claims with IAM roles mapped to Kubernetes groups
        custom_claims = {
            "gcp.iam.roles": k8s_groups,
            "gcp.project": PROJECT_ID
        }
        
        claims_success, claims_result = set_custom_claims(user_id, custom_claims, PROJECT_ID)
        
        # Get a fresh token with the custom claims
        # We need to exchange again to get a token with the new claims
        if claims_success:
            # Re-exchange to get token with custom claims
            req = urllib.request.Request(
                f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp?key={IDP_API_KEY}",
                data=idp_data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req) as response:
                idp_response = json.loads(response.read().decode())
            idp_token = idp_response.get("idToken", idp_token)
        
        idp_claims = decode_jwt_claims(idp_token)

        safe_claims = {}
        for key in ("email", "sub", "iss", "aud", "exp", "iat",
                    "gcp.iam.roles", "gcp.project"):
            if key in idp_claims:
                safe_claims[key] = idp_claims[key]

        return jsonify({
            "success": True,
            "idp_token": idp_token,
            "issuer": f"https://securetoken.google.com/{PROJECT_ID}",
            "email": idp_claims.get("email"),
            "iam_roles": iam_roles,
            "k8s_groups": k8s_groups,
            "claims": safe_claims,
            "custom_claims_set": claims_success
        })

    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        logger.error("IDP exchange failed (HTTP %d): %s", e.code, error_body)
        return jsonify({
            "error": "Identity Platform exchange failed",
            "message": "Token exchange with Identity Platform failed"
        }), 500
    except Exception as e:
        logger.exception("IDP exchange error")
        return jsonify({
            "error": "Identity Platform exchange failed",
            "message": "An unexpected error occurred during token exchange"
        }), 500


def show_usage(request):
    """Show usage information."""
    host = request.headers.get("X-Forwarded-Host", request.host)
    proto = request.headers.get("X-Forwarded-Proto", "https")
    base_url = f"{proto}://{host}"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>GCP HCP Token Exchange</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                   max-width: 800px; margin: 40px auto; padding: 20px; background: #f8f9fa; }}
            .card {{ background: white; border-radius: 12px; padding: 24px; margin: 20px 0;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
            code {{ background: #e3f2fd; padding: 2px 6px; border-radius: 4px; }}
            pre {{ background: #263238; color: #aed581; padding: 15px; border-radius: 8px; 
                  overflow-x: auto; font-size: 13px; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🔐 GCP HCP Token Exchange</h1>
            <p>This Cloud Function exchanges Google identity tokens for Identity Platform tokens 
               with IAM role claims for Kubernetes RBAC.</p>
        </div>
        
        <div class="card">
            <h2>Endpoints</h2>
            <ul>
                <li><code>{base_url}/exchange</code> - Exchange gcloud token for IDP token</li>
                <li><code>{base_url}/health</code> - Health check</li>
            </ul>
        </div>
        
        <div class="card">
            <h2>Usage</h2>
            <pre>
# Get a Google identity token
GCLOUD_TOKEN=$(gcloud auth print-identity-token)

# Exchange for IDP token with IAM roles
curl -X POST \\
  -H "Authorization: Bearer $GCLOUD_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{{"google_token": "'$GCLOUD_TOKEN'"}}' \\
  "{base_url}/exchange"
            </pre>
            
            <h3>Or use the gcphcp CLI:</h3>
            <pre>gcphcp clusters login &lt;cluster-name&gt;</pre>
        </div>
        
        <div class="card">
            <h2>Response</h2>
            <p>The exchange endpoint returns:</p>
            <ul>
                <li><code>idp_token</code> - Identity Platform JWT for cluster authentication</li>
                <li><code>iam_roles</code> - User's GCP IAM roles on the project</li>
                <li><code>k8s_groups</code> - Mapped Kubernetes groups (cluster-admin, cluster-viewer)</li>
                <li><code>claims</code> - Full token claims including <code>gcp.iam.roles</code></li>
            </ul>
        </div>
    </body>
    </html>
    """
    return html, 200, {"Content-Type": "text/html"}
