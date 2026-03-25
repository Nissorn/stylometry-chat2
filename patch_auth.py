import os

file_path = "backend/app/auth.py"
with open(file_path, "r") as f:
    text = f.read()

old_func = """def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(database.get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user"""

new_func = """def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(database.get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            print("AUTH FAILED: No sub in payload")
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError as e:
        print(f"AUTH FAILED: JWTError {e}")
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        print(f"AUTH FAILED: User {username} not found in DB")
        raise HTTPException(status_code=401, detail="User not found")
    return user"""

text = text.replace(old_func, new_func)

with open(file_path, "w") as f:
    f.write(text)
print("patch auth done")
