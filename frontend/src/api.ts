export type Link = {id:number; original_url:string; short_code:string; short_url:string; click_count:number; created_at:string; expires_at:string|null};
const API='/api/v1';
export class ApiError extends Error { constructor(public status:number,message:string){super(message);} }
async function request<T>(path:string, options:RequestInit={}, token?:string):Promise<T>{
 const headers:Record<string,string>={'Content-Type':'application/json',...(options.headers as Record<string,string>||{})};
 if(token)headers.Authorization=`Bearer ${token}`;
 let response:Response;
 try {response=await fetch(`${API}${path}`,{...options,headers});}catch{throw new ApiError(0,'Cannot reach the backend. Check that FastAPI is running.');}
 if(!response.ok){const body=await response.json().catch(()=>({}));throw new ApiError(response.status,typeof body.detail==='string'?body.detail:`Request failed (${response.status})`);}
 if(response.status===204)return undefined as T;
 return response.json() as Promise<T>;
}
export const api={
 analytics:(token:string)=>request<{timezone:string;daily:{date:string;clicks:number}[]}>('/analytics/clicks',{},token),
 register:(email:string,password:string)=>request<{access_token:string}>('/auth/register',{method:'POST',body:JSON.stringify({email,password})}),
 login:(email:string,password:string)=>request<{access_token:string}>('/auth/login',{method:'POST',body:JSON.stringify({email,password})}),
 list:(token:string)=>request<Link[]>('/urls',{},token),
 create:(token:string,original_url:string,custom_alias?:string)=>request<Link>('/urls',{method:'POST',body:JSON.stringify({original_url,...(custom_alias?{custom_alias}:{})})},token),
 stats:(token:string,code:string)=>request<{click_count:number}>(`/urls/${encodeURIComponent(code)}/stats`,{},token),
 remove:(token:string,code:string)=>request<void>(`/urls/${encodeURIComponent(code)}`,{method:'DELETE'},token)
};