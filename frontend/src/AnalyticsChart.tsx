import {useMemo} from 'react';

type Point = {date:string; clicks:number};
export default function AnalyticsChart({data,error}:{data:Point[];error:string}){
 const max=useMemo(()=>Math.max(1,...data.map(p=>p.clicks)),[data]);
 return <section className="analytics-panel" aria-label="Click activity">
  <div className="analytics-heading"><div><h2>Click activity</h2><p>Daily redirects recorded in UTC over the last 14 days</p></div><span className="analytics-total">{data.reduce((sum,p)=>sum+p.clicks,0).toLocaleString()} recent clicks</span></div>
  {error?<p role="alert" className="alert error">Analytics unavailable: {error}</p>:
   <div className="analytics-bars" role="img" aria-label={data.map(p=>`${p.date}: ${p.clicks} clicks`).join('; ')||'No analytics yet'}>
    {data.map(p=><div className="analytics-column" key={p.date} title={`${p.date}: ${p.clicks} clicks`}>
     <span className="analytics-count">{p.clicks}</span>
     <div className="analytics-track"><div className="analytics-fill" style={{height:`${Math.max(2,(p.clicks/max)*100)}%`}}/></div>
     <span className="analytics-label">{p.date.slice(5)}</span>
    </div>)}
   </div>}
  <p className="analytics-note">Historical clicks recorded before this upgrade are included in total clicks, but not in this chart.</p>
 </section>;
}
