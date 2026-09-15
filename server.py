import asyncio
import base64
import hashlib
import json
import os
import random
import struct
from collections import Counter

HOST="0.0.0.0"
PORT=int(os.environ.get("PORT","8765"))
VERSION="v1.00.34"
DATA_FILE=os.environ.get("RNG_DATA_FILE","rng_adventure_saves.json")

ITEMS={
"Rotten_Sword":[5,50],"Wooden_Sword":[10,40],"Stone_Sword":[15,30],"Gold_sword":[20,15],
"Diamond_sword":[25,10],"Netherite_Sword":[30,5],"Mythicite_Sword":[35,3],"Ultracult_Sword":[40,1],
"Divinite_Sword":[45,.8],"Sigma_Sword":[50,.75],"Aurarizz_Sword":[55,.5],"Glock_15":[60,.4],
"Glock_16":[65,.3],"Glock_17":[70,.15],"Glock_18":[75,.1],"Glock_19":[250,.15],"Ak_47":[500,.1],
"Leather_Armor":[5,50],"Stone_Armor":[10,40],"Iron_Armor":[15,35],"Gold_Armor":[20,30],
"Diamond_Armor":[25,20],"Netherite_Armor":[30,10],"Mythicite_Armor":[35,1.5],"Ultracult_Armor":[40,1],
"Divinite_Armor":[45,.5],"Sigma_Armor":[50,.3],"Aurarizz_Armor":[75,.2],"Da_Drip":[100,.15],
"Liquid_Gold":[250,.1],"Lightning?????":[500,.05],"Dark_matter":[750,.02],"AC_130":[750,.01]
}
MONSTERS={"Angry_traveler":[25,50],"Zombie":[35,40],"Skeleton":[40,35],"Bro_from_school":[45,30],
"Lil_Tim":[50,20],"Rizzler":[55,15],"School":[60,10],"That_one_kid":[65,5],"Ur_mom":[70,3.5],
"Grim_Reaper":[75,1],"Your_Boss":[80,.5]}
ADMIN_MONSTERS={"67_Kid":100,"Kong_FU_PANDA":250,"MRRRRRRR_BEEEAAST":500,"Verity":750}
ADMIN_GEAR={"Admin_Sword":100,"Ultra_Admin_Sword":250,"Secret_Admin_Sword":500,"Dev_Sword":750,
"Admin_Armor":100,"Ultra_Admin_Armor":250,"Secret_Admin_Armor":500,"Dev_Armor":750}
ADMIN_KEYS={"banana":"admin","beans":"ultra admin","grape":"secret admin","green bean":"developer"}
TIERS=["player","admin","ultra admin","secret admin","developer"]

def blank_save():
    return {"name":"","aura":0,"inventory":["Wooden_Sword"],"weapon_luck":1.0,
            "monster_luck":1.0,"admin":"player","forced":None}

def load_db():
    try:
        with open(DATA_FILE,"r",encoding="utf-8") as f:
            x=json.load(f)
            return x if isinstance(x,dict) else {}
    except (FileNotFoundError,json.JSONDecodeError,OSError):
        return {}

db=load_db()
db_lock=asyncio.Lock()

def save_db():
    tmp=DATA_FILE+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(db,f,separators=(",",":"))
    os.replace(tmp,DATA_FILE)

def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

class Player:
    def __init__(self,ws,name="Player"):
        self.ws=ws; self.name=(name or "Player")[:24]
        self.aura=0; self.inventory=["Wooden_Sword"]; self.weapon_luck=1.0
        self.monster_luck=1.0; self.admin="player"; self.forced=None
        self.username=None; self.slot=1

players={}
lock=asyncio.Lock()

def weighted(obj,luck):
    entries=list(obj.items())
    weights=[v[1]*(max(.01,luck) if v[1]<10 else 1) for _,v in entries]
    r=random.random()*sum(weights)
    for (name,_),w in zip(entries,weights):
        r-=w
        if r<=0:return name
    return entries[-1][0]

def required_tier(item):
    if item in ("Admin_Sword","Admin_Armor"):return "admin"
    if item in ("Ultra_Admin_Sword","Ultra_Admin_Armor"):return "ultra admin"
    if item in ("Secret_Admin_Sword","Secret_Admin_Armor"):return "secret admin"
    if item in ("Dev_Sword","Dev_Armor"):return "developer"
    return None

def best_weapon(p):
    best="None"; power=0
    for x in p.inventory:
        if "Sword" in x or x=="AC_130":
            v=ITEMS.get(x,[0])[0] if x in ITEMS else ADMIN_GEAR.get(x,0)
            if v>power:best,power=x,v
    return best,power

def best_armor(p):
    best="None"; defense=0
    for x in p.inventory:
        if "Armor" in x:
            v=ITEMS.get(x,[0])[0] if x in ITEMS else ADMIN_GEAR.get(x,0)
            if v>defense:best,defense=x,v
    return best,defense

def save_player(p):
    if not p.username:return
    account=db.get(p.username)
    if not account:return
    slots=account.setdefault("slots",[blank_save(),blank_save(),blank_save()])
    s=slots[max(0,min(2,p.slot-1))]
    s.update({"name":p.name,"aura":int(p.aura),"inventory":list(p.inventory),
              "weapon_luck":float(p.weapon_luck),"monster_luck":float(p.monster_luck),
              "admin":p.admin,"forced":p.forced})
    save_db()

def load_player(p,username,slot):
    account=db[username]
    s=account.setdefault("slots",[blank_save(),blank_save(),blank_save()])[slot-1]
    p.username=username;p.slot=slot;p.name=(s.get("name") or username)[:24]
    p.aura=int(s.get("aura",0));p.inventory=list(s.get("inventory") or ["Wooden_Sword"])
    p.weapon_luck=float(s.get("weapon_luck",1.0));p.monster_luck=float(s.get("monster_luck",1.0))
    p.admin=s.get("admin","player");p.forced=s.get("forced")

async def send(ws,data):
    payload=json.dumps(data,separators=(",",":")).encode()
    n=len(payload); header=bytes([0x81])
    if n<126:header+=bytes([n])
    elif n<65536:header+=bytes([126])+struct.pack(">H",n)
    else:header+=bytes([127])+struct.pack(">Q",n)
    ws.write(header+payload);await ws.drain()

async def recv(reader,writer):
    h=await reader.readexactly(2);opcode=h[0]&15;masked=bool(h[1]&128);n=h[1]&127
    if n==126:n=struct.unpack(">H",await reader.readexactly(2))[0]
    elif n==127:n=struct.unpack(">Q",await reader.readexactly(8))[0]
    mask=await reader.readexactly(4) if masked else b""
    data=bytearray(await reader.readexactly(n))
    if masked:
        for i in range(n):data[i]^=mask[i%4]
    if opcode==8:return None
    if opcode==9:
        plen=len(data); header=bytes([0x8A,plen]) if plen<126 else bytes([0x8A,126])+struct.pack(">H",plen)
        writer.write(header+bytes(data));await writer.drain();return await recv(reader,writer)
    return bytes(data).decode("utf-8") if opcode==1 else ""

def state(p):
    return {"type":"state","player":{"name":p.name,"aura":p.aura,"inventory":p.inventory,
    "weapon_luck":p.weapon_luck,"monster_luck":p.monster_luck,"admin_level":p.admin,
    "forced_enemy_name":p.forced,"username":p.username,"slot":p.slot}}

async def do_action(p,m):
    a=m.get("action")
    if a=="account":
        u=str(m.get("username","")).strip().lower()[:32]; pw=str(m.get("password",""))
        if len(u)<3 or len(pw)<4:return await send(p.ws,{"type":"error","message":"Username must be 3+ characters and password 4+ characters."})
        async with db_lock:
            existing=db.get(u)
            if existing and existing.get("password")!=hash_password(pw):
                return await send(p.ws,{"type":"error","message":"Incorrect password."})
            if not existing:
                db[u]={"password":hash_password(pw),"slots":[blank_save(),blank_save(),blank_save()]}
                save_db()
            p.username=u
        await send(p.ws,{"type":"account_ok","username":u,"slots":[s.get("name","") for s in db[u]["slots"]]})
        return
    if a=="load_slot":
        if not p.username:return await send(p.ws,{"type":"error","message":"Sign in first."})
        slot=int(m.get("slot",1))
        if slot not in (1,2,3):return await send(p.ws,{"type":"error","message":"Invalid save slot."})
        async with db_lock:load_player(p,p.username,slot)
        await send(p.ws,{"type":"slot_loaded","slot":slot});await send(p.ws,state(p));return
    if a=="save":
        async with db_lock:save_player(p)
        await send(p.ws,{"type":"saved","slot":p.slot});return
    if a=="reset_slot":
        if not p.username:return await send(p.ws,{"type":"error","message":"Sign in first."})
        slot=int(m.get("slot",p.slot))
        if slot not in (1,2,3):return await send(p.ws,{"type":"error","message":"Invalid save slot."})
        async with db_lock:
            db[p.username]["slots"][slot-1]=blank_save()
            if p.slot==slot:load_player(p,p.username,slot)
            save_db()
        await send(p.ws,{"type":"slot_reset","slot":slot});await send(p.ws,state(p));return
    if a=="leaderboard":
        rows=[]
        async with db_lock:
            for u,acc in db.items():
                for i,s in enumerate(acc.get("slots",[]),1):
                    rows.append({"name":s.get("name") or u,"aura":int(s.get("aura",0)),"slot":i})
        rows.sort(key=lambda x:x["aura"],reverse=True)
        await send(p.ws,{"type":"leaderboard","players":rows[:100]});return
    if a=="join":
        p.name=(m.get("name") or p.name)[:24]
        await send(p.ws,{"type":"welcome","version":VERSION,"name":p.name});await send(p.ws,state(p))
        await broadcast({"type":"log","message":f"🟢 {p.name} joined the server."});return
    if a=="roll":
        x=weighted(ITEMS,p.weapon_luck);p.inventory.append(x)
        await send(p.ws,state(p))
        await send(p.ws,{"type":"result","text":f"🎲 You rolled {x}! | Value: {ITEMS[x][0]}"})
        if p.username:
            async with db_lock:save_player(p)
        return
    if a=="inventory":
        c=Counter(p.inventory);text="🎒 INVENTORY\n"+"\n".join(f"{x} x{n}" for x,n in sorted(c.items()))
        await send(p.ws,{"type":"result","text":text});return
    if a=="stats":
        w,wp=best_weapon(p);ar,ap=best_armor(p)
        await send(p.ws,{"type":"result","text":f"📊 PLAYER STATS\n\nAdmin Rank: {p.admin}\nAura: {p.aura}\nWeapon Luck: {p.weapon_luck:.2f}x\nMonster Luck: {p.monster_luck:.2f}x\nInventory: {len(p.inventory)} items\nBest Weapon: {w} (+{wp})\nBest Armor: {ar} (+{ap})"});return
    if a=="event":
        if p.forced:enemy=p.forced;p.forced=None;isboss=enemy in ADMIN_MONSTERS
        else:
            isboss=(random.randint(1,10000)<=min(10000,max(1,int(p.monster_luck))))
            enemy=random.choice(list(ADMIN_MONSTERS)) if isboss else weighted(MONSTERS,p.monster_luck)
        hp=ADMIN_MONSTERS[enemy] if isboss else MONSTERS[enemy][0];reward=int(hp*(2.5 if isboss else .8))
        w,dmg=best_weapon(p);ar,defn=best_armor(p)
        if dmg>=hp:p.aura+=reward;out=f"🏆 FLAWLESS! You defeated {enemy} and gained +{reward} Aura!"
        elif dmg+defn>=hp:gain=int(reward*.7);p.aura+=gain;out=f"🛡️ NARROW VICTORY! You defeated {enemy} and gained +{gain} Aura!"
        elif defn:out=f"💀 DEFEAT! {enemy} was too strong, but {ar} protected your Aura."
        else:loss=50 if isboss else 10;p.aura=max(0,p.aura-loss);out=f"💀 DEFEAT! {enemy} was too strong. You lost {loss} Aura."
        await send(p.ws,state(p));await send(p.ws,{"type":"result","text":f"👾 {enemy} appeared! Health: {hp}{' 👑 ADMIN BOSS' if isboss else ''}\nBuild: {w} (+{dmg}) / {ar} (+{defn})\n{out}"})
        if p.username:
            async with db_lock:save_player(p)
        return
    if a=="sell":
        c=Counter(p.inventory);total=0;new=[];seen=set()
        for x in p.inventory:
            if c[x]>1:
                if x not in seen:
                    seen.add(x);new.append(x);total+=(c[x]-1)*((ITEMS.get(x,[500])[0] if x in ITEMS else ADMIN_GEAR.get(x,500))//4)
            else:new.append(x)
        if total:
            p.inventory=new;p.aura+=total;await send(p.ws,state(p));await send(p.ws,{"type":"result","text":f"💰 Sold duplicates for +{total} Aura."})
        else:await send(p.ws,{"type":"result","text":"✨ You don't have any duplicate items to sell."})
        if p.username:
            async with db_lock:save_player(p)
        return
    if a=="upgrade_luck":
        kind=m.get("kind");maximum=bool(m.get("maximum"));attr="weapon_luck" if kind=="weapon" else "monster_luck"
        current=getattr(p,attr);spent=0;count=0
        while True:
            cost=max(1,int(15*(current**1.5)))
            if p.aura<cost:break
            p.aura-=cost;spent+=cost;current+=max(.05,.5/current);count+=1
            if not maximum:break
        setattr(p,attr,current);await send(p.ws,state(p))
        await send(p.ws,{"type":"result","text":f"🍀 {kind.title()} Luck is now {current:.2f}x. Spent {spent} Aura." if count else "Not enough Aura for an upgrade."})
        if p.username:
            async with db_lock:save_player(p)
        return
    if a=="admin_login":
        rank=ADMIN_KEYS.get(str(m.get("key","")).strip().lower())
        if rank:
            p.admin=rank;await send(p.ws,state(p));await send(p.ws,{"type":"result","text":f"📢 {p.name} has joined as {rank.upper()}!"})
            if p.username:
                async with db_lock:save_player(p)
        else:await send(p.ws,{"type":"error","message":"Invalid admin key."})
        return
    if a=="admin_give":
        x=str(m.get("item","")).strip();req=required_tier(x)
        if req and TIERS.index(p.admin)>=TIERS.index(req):
            p.inventory.append(x);await send(p.ws,state(p));await send(p.ws,{"type":"result","text":f"🛠 Admin gave you {x}."})
            if p.username:
                async with db_lock:save_player(p)
        else:await send(p.ws,{"type":"error","message":"Item not recognized or rank too low."})
        return
    if a=="admin_spawn":
        x=str(m.get("enemy","")).strip()
        if x in MONSTERS or x in ADMIN_MONSTERS:p.forced=x;await send(p.ws,{"type":"result","text":f"🛠 Next Event will force {x}."})
        else:await send(p.ws,{"type":"error","message":"Monster name not recognized."})
        return
    if a=="chat":
        msg=str(m.get("message","")).strip()[:300]
        if msg:await broadcast({"type":"chat","name":p.name,"rank":p.admin.upper(),"message":msg})
        return
    if a=="admin_set":
        kind=str(m.get("kind",""))
        try:v=float(m.get("value"))
        except (TypeError,ValueError):v=-1
        if kind=="aura" and v>=0:p.aura=int(v)
        elif kind=="weapon" and v>=.01:p.weapon_luck=v
        elif kind=="monster" and v>=.01:p.monster_luck=v
        else:return await send(p.ws,{"type":"error","message":"Invalid value."})
        await send(p.ws,state(p))
        if p.username:
            async with db_lock:save_player(p)
        return
    if a=="update_log":
        await send(p.ws,{"type":"result","text":"v1.00.34\n• WebSocket multiplayer server.\n• Render online support.\n• Account saves and 3 save slots.\n• Global Aura leaderboard.\n• Reset Progress for selected slot."})

async def broadcast(data,exclude=None):
    for q in list(players.values()):
        if q.ws is not exclude:
            try:await send(q.ws,data)
            except:pass

async def client(reader,writer):
    p=None;ws=None;peer=writer.get_extra_info("peername")
    try:
        request=await reader.readuntil(b"\r\n\r\n");headers=request.decode("latin1").split("\r\n");h={}
        for line in headers[1:]:
            if ":" in line:k,v=line.split(":",1);h[k.lower().strip()]=v.strip()
        key=h.get("sec-websocket-key")
        if not key:
            body=b"RNG Adventure Online OK"
            response=("HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\n"
                      f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode()+body
            writer.write(response);await writer.drain();return
        accept=base64.b64encode(hashlib.sha1((key+"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode());await writer.drain();ws=writer
        while True:
            raw=await recv(reader,writer)
            if raw is None:break
            try:m=json.loads(raw)
            except:continue
            if p is None:
                if m.get("action") not in ("account","leaderboard"):continue
                p=Player(ws,m.get("username") or m.get("name","Player"));players[id(ws)]=p
            async with lock:await do_action(p,m)
    except (asyncio.IncompleteReadError,ConnectionError,OSError):pass
    except Exception as e:print(f"Client error {peer}: {type(e).__name__}: {e}")
    finally:
        if p:players.pop(id(ws),None)
        try:writer.close();await writer.wait_closed()
        except:pass
        print("Disconnected:",peer)

async def main():
    server=await asyncio.start_server(client,HOST,PORT)
    print(f"RNG Adventure Online {VERSION} WebSocket server listening on ws://{HOST}:{PORT}",flush=True)
    print("Persistent save file:",DATA_FILE,flush=True)
    print("Press Ctrl+C to stop.",flush=True)
    async with server:await server.serve_forever()

if __name__=="__main__":
    try:asyncio.run(main())
    except KeyboardInterrupt:print("\nServer stopped.")
