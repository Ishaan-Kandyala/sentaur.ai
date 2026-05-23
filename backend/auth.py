import os
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from passlib.context import CryptContext
import jwt
from sqlalchemy.orm import Session
from authlib.integrations.starlette_client import OAuth
from .database import get_db
from .models import User
from .tools import send_email

router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

oauth = OAuth()

MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")

if MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET:
    oauth.register(
        name="microsoft",
        client_id=MICROSOFT_CLIENT_ID,
        client_secret=MICROSOFT_CLIENT_SECRET,
        server_metadata_url="https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

class SignupRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.now() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_or_create_oauth_user(db: Session, email: str) -> str:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, password_hash="")
        db.add(user)
        db.commit()
        db.refresh(user)
    return create_access_token({"sub": str(user.id)})

@router.post("/signup", response_model=TokenResponse)
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=req.email, password_hash=hash_password(req.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token)

@router.post("/login", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Invalid credentials")
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token)

def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)) -> User:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

@router.get("/microsoft")
async def microsoft_login(request: Request):
    if not MICROSOFT_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Microsoft OAuth not configured")
    redirect_uri = str(request.url_for("microsoft_callback"))
    return await oauth.microsoft.authorize_redirect(request, redirect_uri)

@router.get("/microsoft/callback", name="microsoft_callback")
async def microsoft_callback(request: Request, db: Session = Depends(get_db)):
    token = await oauth.microsoft.authorize_access_token(request)
    email = token["userinfo"]["email"]
    access_token = get_or_create_oauth_user(db, email)
    return RedirectResponse(url=f"/chat.html?token={access_token}")

@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        return {"message": "If that email exists, a reset link has been sent."}
    reset_token = create_access_token({"sub": str(user.id), "type": "reset"}, timedelta(hours=1))
    base_url = os.getenv("BASE_URL", "https://sentaur-ai.onrender.com")
    reset_link = f"{base_url}/reset-password.html?token={reset_token}"
    send_email(
        to_email=user.email,
        subject="Reset your Sentaur AI password",
        body=f"Click the link below to reset your password (expires in 1 hour):\n\n{reset_link}"
    )
    return {"message": "If that email exists, a reset link has been sent."}

@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(req.token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "reset":
            raise ValueError()
        user_id = int(payload.get("sub"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=400, detail="User not found")
    user.password_hash = hash_password(req.new_password)
    db.commit()
    return {"message": "Password reset successfully"}
