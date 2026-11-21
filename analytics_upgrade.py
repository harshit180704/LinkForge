from pathlib import Path
import shutil

root=Path(__file__).resolve().parent
paths=[root/'app/models.py',root/'app/worker.py',root/'app/main.py',root/'frontend/src/api.ts',root/'frontend/src/App.tsx',root/'frontend/src/styles.css']
if any(not p.exists() for p in paths):
    raise SystemExit('Run from existing scalable-url-shortener root after setting up frontend.')
models,worker,main,api,frontend,styles=[p.read_text(encoding='utf-8') for p in paths]
if 'class ClickEvent(' in models or 'def dashboard_click_analytics(' in main:
    raise SystemExit('Analytics upgrade already applied or partially applied. Check files before rerunning.')
checks=[('worker', 'db.add(ProcessedClick(event_id=event_id))' in worker),('model', 'class ProcessedClick(' in models),('main', 'from app.models import ShortURL, User' in main),('api', 'export const api={' in api),('frontend', 'import {api,ApiError,type Link}' in frontend)]
if not all(ok for _,ok in checks):
    raise SystemExit('Source files differ from expected versions: '+str(checks)+'; no files changed.')
backup=root/'analytics-backup'
if backup.exists():
    raise SystemExit('analytics-backup already exists. No changes made.')
for p in paths:
    target=backup/p.relative_to(root)
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(p,target)
models+='\nclass ClickEvent(Base):\n    __tablename__ = "click_events"\n    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)\n    url_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)\n    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)\n'
worker=worker.replace('from app.models import ProcessedClick, ShortURL','from app.models import ClickEvent, ProcessedClick, ShortURL')
worker=worker.replace('db.add(ProcessedClick(event_id=event_id))','db.add(ProcessedClick(event_id=event_id))\n            db.add(ClickEvent(event_id=event_id, url_id=url_id))')
main=main.replace('from app.models import ShortURL, User','from app.models import ClickEvent, ShortURL, User')
main=main.replace('from datetime import datetime, timezone','from datetime import date, datetime, timedelta, timezone')
main=main.replace('from sqlalchemy import select, text','from sqlalchemy import select, text, func')
main+='\n@app.get("/api/v1/analytics/clicks")\ndef dashboard_click_analytics(db: Session = Depends(get_db), user: User = Depends(current_user)):\n    """14-day UTC click histogram for the authenticated user\'s active links."""\n    today = datetime.now(timezone.utc).date()\n    first = today - timedelta(days=13)\n    start = datetime.combine(first, datetime.min.time(), tzinfo=timezone.utc)\n    utc_date = func.date(func.timezone("UTC", ClickEvent.clicked_at))\n    rows = db.execute(\n        select(utc_date.label("date"), func.count(ClickEvent.event_id))\n        .join(ShortURL, ShortURL.id == ClickEvent.url_id)\n        .where(ShortURL.owner_id == user.id, ClickEvent.clicked_at >= start)\n        .group_by(utc_date)\n        .order_by(utc_date)\n    ).all()\n    totals = {str(day): count for day, count in rows}\n    return {"timezone": "UTC", "daily": [\n        {"date": (first + timedelta(days=i)).isoformat(),\n         "clicks": totals.get((first + timedelta(days=i)).isoformat(), 0)}\n        for i in range(14)\n    ]}\n'
api=api.replace('export const api={', "export const api={\n analytics:(token:string)=>request<{timezone:string;daily:{date:string;clicks:number}[]}>('/analytics/clicks',{},token),")
# Existing frontend is modified with narrowly scoped replacements below.
frontend=frontend.replace("import {api,ApiError,type Link} from './api';", "import {api,ApiError,type Link} from './api';\nimport AnalyticsChart from './AnalyticsChart';",1)
frontend=frontend.replace(' const [token,setToken]=useState'," const [analytics,setAnalytics]=useState<{date:string;clicks:number}[]>([]);\n const [analyticsError,setAnalyticsError]=useState('');\n const [token,setToken]=useState",1)
frontend=frontend.replace("setLinks(await api.list(token));setError('');", "setLinks(await api.list(token));setError('');try{const result=await api.analytics(token);setAnalytics(result.daily);setAnalyticsError('');}catch(e){setAnalyticsError((e as Error).message);}",1)
frontend=frontend.replace('</section><section className="create-panel">','</section><AnalyticsChart data={analytics} error={analyticsError}/><section className="create-panel">',1)
if 'AnalyticsChart data={analytics}' not in frontend:
    raise SystemExit('Could not locate dashboard statistics panel; backups saved but originals untouched.')
updates={paths[0]:models,paths[1]:worker,paths[2]:main,paths[3]:api,paths[4]:frontend,paths[5]:styles+'\n/* Analytics time-series */\n.analytics-panel{background:#fff;border:1px solid #e7eaf4;border-radius:18px;padding:28px 32px;margin:24px 0}\n.analytics-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}\n.analytics-heading h2{font-size:20px;margin:0 0 5px}\n.analytics-heading p,.analytics-note{font-size:13px;color:#8995ad;margin:0}\n.analytics-total{font-size:13px;font-weight:700;color:#6750df;background:#f1edff;border-radius:20px;padding:9px 13px}\n.analytics-bars{display:flex;align-items:end;gap:10px;height:235px;padding-top:24px;margin-top:20px;overflow-x:auto}\n.analytics-column{flex:1;min-width:27px;height:100%;display:flex;flex-direction:column;align-items:center;gap:7px}\n.analytics-count{font-size:11px;color:#69748d}\n.analytics-track{height:100%;width:100%;max-width:55px;display:flex;align-items:end;background:#f5f3ff;border-radius:7px 7px 0 0;overflow:hidden}\n.analytics-fill{width:100%;background:linear-gradient(180deg,#8c79f7,#6652e8);border-radius:7px 7px 0 0;min-height:2px}\n.analytics-label{font-size:10px;color:#8893a7;white-space:nowrap}\n.analytics-note{margin-top:20px}\n/* Sidebar navigation as real buttons */\nbutton.side-link{font:inherit;text-align:left;width:100%;border:0;cursor:pointer;background:transparent}\nbutton.side-link.active{background:#f0edff}\n'}
for p,content in updates.items():
    p.write_text(content,encoding='utf-8')
(root/'frontend/src/AnalyticsChart.tsx').write_text('import {useMemo} from \'react\';\n\ntype Point = {date:string; clicks:number};\nexport default function AnalyticsChart({data,error}:{data:Point[];error:string}){\n const max=useMemo(()=>Math.max(1,...data.map(p=>p.clicks)),[data]);\n return <section className="analytics-panel" aria-label="Click activity">\n  <div className="analytics-heading"><div><h2>Click activity</h2><p>Daily redirects recorded in UTC over the last 14 days</p></div><span className="analytics-total">{data.reduce((sum,p)=>sum+p.clicks,0).toLocaleString()} recent clicks</span></div>\n  {error?<p role="alert" className="alert error">Analytics unavailable: {error}</p>:\n   <div className="analytics-bars" role="img" aria-label={data.map(p=>`${p.date}: ${p.clicks} clicks`).join(\'; \')||\'No analytics yet\'}>\n    {data.map(p=><div className="analytics-column" key={p.date} title={`${p.date}: ${p.clicks} clicks`}>\n     <span className="analytics-count">{p.clicks}</span>\n     <div className="analytics-track"><div className="analytics-fill" style={{height:`${Math.max(2,(p.clicks/max)*100)}%`}}/></div>\n     <span className="analytics-label">{p.date.slice(5)}</span>\n    </div>)}\n   </div>}\n  <p className="analytics-note">Historical clicks recorded before this upgrade are included in total clicks, but not in this chart.</p>\n </section>;\n}\n',encoding='utf-8')
with (root/'.gitignore').open('a',encoding='utf-8') as f:
    f.write('\nanalytics-backup/\n')
print('Advanced analytics installed. Source backups: analytics-backup/')
print('Restart FastAPI FIRST (creates click_events), then restart worker, then npm run dev.')
