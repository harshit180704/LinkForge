from pathlib import Path
import shutil
root = Path(__file__).resolve().parent
main = root / 'app' / 'main.py'
if not main.exists():
    raise SystemExit('Run this from the existing scalable-url-shortener project root')
src = main.read_text(encoding='utf-8')
if 'dashboard_url_list' not in src:
    backup = root / 'app' / 'main.before_dashboard.py.bak'
    if not backup.exists():
        shutil.copy2(main, backup)
    addition = '''

@app.get("/api/v1/urls", response_model=list[URLResponse])
def dashboard_url_list(db: Session = Depends(get_db), user: User = Depends(current_user)):
    urls = db.scalars(
        select(ShortURL).where(ShortURL.owner_id == user.id).order_by(ShortURL.created_at.desc())
    ).all()
    return [response_for(url) for url in urls]
'''
    main.write_text(src + addition, encoding='utf-8')
    print('Added GET /api/v1/urls. Original main.py backed up at', backup)
else:
    print('List endpoint already installed')
print('Vite proxy handles /api locally, so no CORS changes are needed.')
