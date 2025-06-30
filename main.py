# -*- coding: utf-8 -*-
"""
Bot de Discord para gestión de DNIs y antecedentes (texto),
con control de acceso por roles, compartir DNI bajo consentimiento
y anuncio automático en canal al crear un nuevo DNI.
"""

import re
import json
import os
import webserver
import datetime
import asyncio

import discord
from discord import app_commands
from discord.ext import commands
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

ADMIN_ROLE_IDS    = [1353412512208388189, 1353412517514449049]  # IDs de admins
POLICE_ROLE_IDS   = [1370000000000000000]                      # ID del rol "policías"
ANNOUNCE_CHANNEL_ID = [1353412567589982330, 1353412547558248571]

def tiene_rol_admin(inter: discord.Interaction) -> bool:
    if not isinstance(inter.user, discord.Member):
        return False
    return any(r.id in ADMIN_ROLE_IDS for r in inter.user.roles)

def tiene_rol_policia(inter: discord.Interaction) -> bool:
    if not isinstance(inter.user, discord.Member):
        return False
    return any(r.id in POLICE_ROLE_IDS for r in inter.user.roles) or tiene_rol_admin(inter)

def solo_admin():
    return app_commands.check(lambda inter: tiene_rol_admin(inter))

def solo_policia():
    return app_commands.check(lambda inter: tiene_rol_policia(inter))

# ───── Persistencia JSON ─────
DNI_FILE   = "dni_data.json"
ANTEC_FILE = "antecedentes_data.json"

def load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

dni_db   = load_json(DNI_FILE)
antec_db = load_json(ANTEC_FILE)

# ───── Bot y sincronización ─────
bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Bot activo como {bot.user}")

@bot.tree.error
async def on_app_command_error(inter: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        await inter.response.send_message("🚫 No tienes permiso para usar este comando.", ephemeral=True)
    else:
        raise error

# ───── Modales ─────
class CrearDNIModal(discord.ui.Modal, title="Registrar DNI"):
    nombre     = discord.ui.TextInput(label="Nombre", max_length=30)
    apellidos  = discord.ui.TextInput(label="Apellidos", max_length=60)
    dni        = discord.ui.TextInput(label="DNI (9 números + 1 letra)", min_length=10, max_length=10)
    nacimiento = discord.ui.TextInput(label="Nacimiento (DD/MM/AAAA)", min_length=10, max_length=10)
    sex_nat    = discord.ui.TextInput(label="Sexo y nacionalidad (H/M ESP)", placeholder="M ESP", max_length=7)

    async def on_submit(self, interaction: discord.Interaction):
        uid  = str(interaction.user.id)
        nom  = self.nombre.value.strip()
        ape  = self.apellidos.value.strip()
        dni_ = self.dni.value.strip().upper()
        nac  = self.nacimiento.value.strip()
        try:
            sexo, nacio = re.split(r"[ ,]+", self.sex_nat.value.strip().upper(), maxsplit=1)
        except ValueError:
            return await interaction.response.send_message("❌ Formato: H/M ESP", ephemeral=True)

        data = {
            "nombre":       nom,
            "apellidos":    ape,
            "dni":          dni_,
            "nacimiento":   nac,
            "sexo":         sexo,
            "nacionalidad": nacio,
            "expedicion":   datetime.date.today().strftime("%d/%m/%Y"),
            "caducidad":    datetime.date.today().replace(year=datetime.date.today().year + 10).strftime("%d/%m/%Y")
        }

        if not re.fullmatch(r"\d{9}[A-Z]", data["dni"]):
            return await interaction.response.send_message("❌ DNI inválido.", ephemeral=True)
        if sexo not in {"H", "M"}:
            return await interaction.response.send_message("❌ Sexo debe ser H o M.", ephemeral=True)
        if not re.fullmatch(r"[A-Z]{3}", data["nacionalidad"]):
            return await interaction.response.send_message("❌ Nacionalidad debe ser 3 letras.", ephemeral=True)
        for rec in dni_db.values():
            if rec["dni"] == data["dni"]:
                return await interaction.response.send_message("❌ Ese DNI ya existe.", ephemeral=True)

        dni_db[uid] = data
        save_json(DNI_FILE, dni_db)
        await interaction.response.send_message("✅ DNI registrado.", ephemeral=True)

        canal = interaction.client.get_channel(ANNOUNCE_CHANNEL_ID)
        if canal:
            emb = discord.Embed(
                title="🆕 Nuevo DNI registrado",
                description=f"Usuario: {interaction.user.mention}",
                color=0x2ECC71
            )
            for k in ["nombre","apellidos","dni","nacimiento","sexo","nacionalidad","expedicion","caducidad"]:
                emb.add_field(name=k.capitalize(), value=data.get(k,"—"), inline=False)
            await canal.send(embed=emb)

class AñadirDNIModal(discord.ui.Modal, title="Registrar DNI para usuario"):
    nombre     = discord.ui.TextInput(label="Nombre", max_length=30)
    apellidos  = discord.ui.TextInput(label="Apellidos", max_length=60)
    dni        = discord.ui.TextInput(label="DNI (9 números + 1 letra)", min_length=10, max_length=10)
    nacimiento = discord.ui.TextInput(label="Nacimiento (DD/MM/AAAA)", min_length=10, max_length=10)
    sex_nat    = discord.ui.TextInput(label="Sexo y nacionalidad (H/M ESP)", placeholder="M ESP", max_length=7)

    def __init__(self, target: discord.Member):
        super().__init__()
        self.target = target
        self.uid    = str(target.id)

    async def on_submit(self, interaction: discord.Interaction):
        nom, ape = self.nombre.value.strip(), self.apellidos.value.strip()
        dni_, nac = self.dni.value.strip().upper(), self.nacimiento.value.strip()
        try:
            sexo, nacio = re.split(r"[ ,]+", self.sex_nat.value.strip().upper(), maxsplit=1)
        except ValueError:
            return await interaction.response.send_message("❌ Formato: H/M ESP", ephemeral=True)

        data = {
            "nombre":       nom,
            "apellidos":    ape,
            "dni":          dni_,
            "nacimiento":   nac,
            "sexo":         sexo,
            "nacionalidad": nacio,
            "expedicion":   datetime.date.today().strftime("%d/%m/%Y"),
            "caducidad":    datetime.date.today().replace(year=datetime.date.today().year + 10).strftime("%d/%m/%Y")
        }

        if not re.fullmatch(r"\d{9}[A-Z]", data["dni"]):
            return await interaction.response.send_message("❌ DNI inválido.", ephemeral=True)
        if sexo not in {"H", "M"}:
            return await interaction.response.send_message("❌ Sexo debe ser H o M.", ephemeral=True)
        if not re.fullmatch(r"[A-Z]{3}", data["nacionalidad"]):
            return await interaction.response.send_message("❌ Nacionalidad debe ser 3 letras.", ephemeral=True)
        for rec in dni_db.values():
            if rec["dni"] == data["dni"]:
                return await interaction.response.send_message("❌ Ese DNI ya existe.", ephemeral=True)

        dni_db[self.uid] = data
        save_json(DNI_FILE, dni_db)
        await interaction.response.send_message(f"✅ DNI registrado para {self.target.mention}.", ephemeral=True)

        canal = interaction.client.get_channel(ANNOUNCE_CHANNEL_ID)
        if canal:
            emb = discord.Embed(
                title="🆕 Nuevo DNI registrado",
                description=f"Usuario: {self.target.mention}",
                color=0x2ECC71
            )
            for k in ["nombre","apellidos","dni","nacimiento","sexo","nacionalidad","expedicion","caducidad"]:
                emb.add_field(name=k.capitalize(), value=data.get(k,"—"), inline=False)
            await canal.send(embed=emb)

class CrearAntecedenteModal(discord.ui.Modal, title="Registrar antecedente"):
    tipo        = discord.ui.TextInput(label="Tipo", max_length=50)
    fecha       = discord.ui.TextInput(label="Fecha (DD/MM/AAAA)", min_length=10, max_length=10)
    descripcion = discord.ui.TextInput(label="Descripción", style=discord.TextStyle.paragraph, max_length=200)
    def __init__(self, uid: int):
        super().__init__(); self.uid = str(uid)
    async def on_submit(self, interaction: discord.Interaction):
        lst = antec_db.setdefault(self.uid, [])
        lst.append({
            "id":           len(lst) + 1,
            "tipo":         self.tipo.value.strip(),
            "fecha":        self.fecha.value.strip(),
            "descripcion":  self.descripcion.value.strip()
        })
        save_json(ANTEC_FILE, antec_db)
        await interaction.response.send_message("✅ Antecedente registrado.", ephemeral=True)

class ResetDNIModal(discord.ui.Modal, title="Eliminar DNI"):
    motivo = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, max_length=200)
    def __init__(self, target: discord.Member):
        super().__init__(); self.target,self.uid = target,str(target.id)
    async def on_submit(self, interaction: discord.Interaction):
        if self.uid in dni_db:
            del dni_db[self.uid]; save_json(DNI_FILE, dni_db)
            try: await self.target.send(f"❗ Tu DNI ha sido eliminado.\nMotivo: {self.motivo.value}")
            except: pass
            await interaction.response.send_message("✅ DNI eliminado.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Ese usuario no tiene DNI.", ephemeral=True)

class QuitarTodosModal(discord.ui.Modal, title="Eliminar TODOS los antecedentes"):
    motivo = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, max_length=200)
    def __init__(self, target: discord.Member):
        super().__init__(); self.target,self.uid = target,str(target.id)
    async def on_submit(self, interaction: discord.Interaction):
        if self.uid in antec_db:
            del antec_db[self.uid]; save_json(ANTEC_FILE, antec_db)
            try: await self.target.send(f"❗ Tus antecedentes han sido eliminados.\nMotivo: {self.motivo.value}")
            except: pass
            await interaction.response.send_message("✅ Antecedentes eliminados.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Ese usuario no tiene antecedentes.", ephemeral=True)

class QuitarUnoModal(discord.ui.Modal, title="Eliminar un antecedente"):
    antecedente_id = discord.ui.TextInput(label="ID", max_length=4)
    motivo         = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, max_length=200)
    def __init__(self, target: discord.Member):
        super().__init__(); self.target,self.uid = target,str(target.id)
    async def on_submit(self, interaction: discord.Interaction):
        lst = antec_db.get(self.uid, [])
        try: aid=int(self.antecedente_id.value)
        except: return await interaction.response.send_message("❌ ID inválido.", ephemeral=True)
        idx = next((i for i,a in enumerate(lst) if a["id"]==aid), None)
        if idx is None:
            return await interaction.response.send_message("❌ ID no existe.", ephemeral=True)
        lst.pop(idx)
        for i,a in enumerate(lst,1): a["id"]=i
        if lst: antec_db[self.uid]=lst
        else:   del antec_db[self.uid]
        save_json(ANTEC_FILE, antec_db)
        try: await self.target.send(f"❗ Antecedente #{aid} eliminado.\nMotivo: {self.motivo.value}")
        except: pass
        await interaction.response.send_message(f"✅ Antecedente #{aid} eliminado.", ephemeral=True)

class ShareDNIView(discord.ui.View):
    def __init__(self, requester: discord.Member, target: discord.Member, tiempo: int):
        super().__init__(timeout=300)
        self.requester = requester
        self.target    = target
        self.tiempo    = tiempo

    @discord.ui.button(label="Aceptar", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            return await interaction.response.send_message("🚫 Solo el destinatario puede aceptar.", ephemeral=True)
        rec = dni_db.get(str(self.target.id))
        if not rec:
            return await interaction.response.send_message("❌ El usuario no tiene DNI.", ephemeral=True)
        dm = self.requester.dm_channel or await self.requester.create_dm()
        emb = discord.Embed(title=f"🔒 DNI de {self.target.display_name}", color=0x2ECC71)
        for k in ["nombre","apellidos","dni","nacimiento","sexo","nacionalidad","expedicion","caducidad"]:
            emb.add_field(name=k.capitalize(), value=rec.get(k,"—"), inline=False)
        msg = await dm.send(embed=emb)
        async def cleanup():
            await asyncio.sleep(self.tiempo)
            try: await msg.delete()
            except: pass
        asyncio.create_task(cleanup())
        await interaction.response.send_message("✅ Has aceptado. DNI enviado y se borrará tras el tiempo indicado.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Rechazar", style=discord.ButtonStyle.secondary)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            return await interaction.response.send_message("🚫 Solo el destinatario puede rechazar.", ephemeral=True)
        await interaction.response.send_message("❌ Has rechazado la solicitud.", ephemeral=True)
        self.stop()

ANT_PAG = 5

def embed_ficha(user, rec, ants, page):
    emb = discord.Embed(title=f"🗂️ Ficha policial de {user.display_name}", color=0xE74C3C)
    emb.add_field(name="Nombre",       value=rec["nombre"],       inline=False)
    emb.add_field(name="Apellidos",    value=rec["apellidos"],    inline=False)
    emb.add_field(name="DNI",          value=rec["dni"],          inline=False)
    emb.add_field(name="Nacimiento",   value=rec.get("nacimiento","—"),   inline=False)
    emb.add_field(name="Nacionalidad", value=rec.get("nacionalidad","—"), inline=False)
    emb.add_field(name="Sexo",         value=rec.get("sexo","—"),         inline=False)
    emb.add_field(name="Expedición",   value=rec.get("expedicion","—"),   inline=False)
    emb.add_field(name="Caducidad",    value=rec.get("caducidad","—"),    inline=False)
    if not ants:
        emb.add_field(name="Antecedentes", value="Sin antecedentes.", inline=False)
    else:
        seg = ants[page*ANT_PAG:(page+1)*ANT_PAG]
        for a in seg:
            emb.add_field(
                name=f"#{a['id']} • {a['tipo']} • {a['fecha']}",
                value=a["descripcion"] or "—", inline=False
            )
        emb.set_footer(text=f"Página {page+1}/{(len(ants)-1)//ANT_PAG+1}")
    return emb

class PaginaView(discord.ui.View):
    def __init__(self, user, rec, ants, req_id):
        super().__init__(timeout=180)
        self.user, self.rec, self.ants, self.req = user, rec, ants, req_id
        self.page = 0
        self.total = (len(ants)-1)//ANT_PAG+1
        self._update_buttons()

    def _update_buttons(self):
        self.prev.disabled = self.page == 0
        self.next.disabled = self.page >= self.total-1

    async def _flip(self, interaction: discord.Interaction, step: int):
        if interaction.user.id != self.req:
            return await interaction.response.send_message("🚫 No puedes navegar esta ficha.", ephemeral=True)
        self.page += step
        self._update_buttons()
        await interaction.response.edit_message(embed=embed_ficha(self.user,self.rec,self.ants,self.page), view=self)

    @discord.ui.button(label="◀ Atrás", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._flip(interaction, -1)

    @discord.ui.button(label="Siguiente ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._flip(interaction, 1)

# ───── Slash-commands ─────
@bot.tree.command(name="creardni", description="Crea tu DNI completo.")
async def creardni(interaction: discord.Interaction):
    if str(interaction.user.id) in dni_db:
        return await interaction.response.send_message("Ya tienes DNI. Usa /verdni.", ephemeral=True)
    await interaction.response.send_modal(CrearDNIModal())

@solo_admin()
@bot.tree.command(name="añadirdni", description="Añade DNI a otro usuario.")
@app_commands.describe(usuario="Usuario destinatario del DNI")
async def anadirdni(interaction: discord.Interaction, usuario: discord.Member):
    if str(usuario.id) in dni_db:
        return await interaction.response.send_message("❌ Ese usuario ya tiene DNI. Usa /verdni.", ephemeral=True)
    await interaction.response.send_modal(AñadirDNIModal(usuario))

@bot.tree.command(name="verdni", description="Muestra tu DNI completo.")
async def verdni(interaction: discord.Interaction):
    rec = dni_db.get(str(interaction.user.id))
    if not rec:
        return await interaction.response.send_message("❌ No tienes DNI.", ephemeral=True)
    emb = discord.Embed(title="🔎 Tu DNI", color=0x3498DB)
    for k in ["nombre","apellidos","dni","nacimiento","nacionalidad","sexo","expedicion","caducidad"]:
        emb.add_field(name=k.capitalize(), value=rec.get(k,"—"), inline=False)
    await interaction.response.send_message(embed=emb, ephemeral=True)

@solo_policia()
@bot.tree.command(name="crearantecedentes", description="Registrar antecedente.")
@app_commands.describe(usuario="Usuario afectado")
async def crearantecedentes(interaction: discord.Interaction, usuario: discord.Member):
    await interaction.response.send_modal(CrearAntecedenteModal(usuario.id))

@solo_admin()
@app_commands.choices(
    quitar_todos=[app_commands.Choice(name="Si", value="Si"),
                  app_commands.Choice(name="No", value="No")]
)
@bot.tree.command(name="quitarantecedentes", description="Eliminar antecedente(s).")
@app_commands.describe(usuario="Usuario afectado", quitar_todos='Elige "Si" para borrar todos')
async def quitarantecedentes(interaction: discord.Interaction, usuario: discord.Member, quitar_todos: app_commands.Choice[str]):
    if quitar_todos.value == "Si":
        await interaction.response.send_modal(QuitarTodosModal(usuario))
    else:
        await interaction.response.send_modal(QuitarUnoModal(usuario))

@solo_admin()
@bot.tree.command(name="reseteardni", description="Eliminar DNI de un usuario.")
@app_commands.describe(usuario="Usuario cuyo DNI eliminarás")
async def reseteardni(interaction: discord.Interaction, usuario: discord.Member):
    await interaction.response.send_modal(ResetDNIModal(usuario))

@solo_policia()
@bot.tree.command(name="fichapolicia", description="Ficha policial de un usuario.")
@app_commands.describe(usuario="Usuario a consultar")
async def fichapolicia(interaction: discord.Interaction, usuario: discord.Member):
    rec = dni_db.get(str(usuario.id))
    if not rec:
        return await interaction.response.send_message(f"❌ {usuario.display_name} no tiene DNI.", ephemeral=True)
    ants = antec_db.get(str(usuario.id), [])
    emb = embed_ficha(usuario, rec, ants, 0)
    if len(ants) > ANT_PAG:
        view = PaginaView(usuario, rec, ants, interaction.user.id)
        await interaction.response.send_message(embed=emb, view=view, ephemeral=True)
    else:
        await interaction.response.send_message(embed=emb, ephemeral=True)

@solo_policia()
@bot.tree.command(name="fichapolicial", description="Alias para /fichapolicia")
@app_commands.describe(usuario="Usuario a consultar")
async def fichapolicial(interaction: discord.Interaction, usuario: discord.Member):
    await fichapolicia(interaction, usuario)

@bot.tree.command(name="ensenardni", description="Solicitar permiso para ver el DNI de un usuario.")
@app_commands.describe(usuario="Usuario dueño del DNI", tiempo="Segundos que durará el DM antes de borrarse")
async def ensenardni(interaction: discord.Interaction, usuario: discord.Member, tiempo: int):
    if str(usuario.id) not in dni_db:
        return await interaction.response.send_message("❌ Ese usuario no tiene DNI.", ephemeral=True)
    await interaction.response.send_message(f"📨 Solicitud enviada a {usuario.display_name}.", ephemeral=True)
    dm = usuario.dm_channel or await usuario.create_dm()
    emb = discord.Embed(
        title="🔔 Solicitud de DNI",
        description=(  
            f"El señor **{interaction.user.display_name}** solicita ver tu DNI.\n"
            "¿Aceptas compartirlo? No se hará ping a nadie."
        ),
        color=0xF1C40F
    )
    view = ShareDNIView(requester=interaction.user, target=usuario, tiempo=tiempo)
    await dm.send(embed=emb, view=view)

# ───── Arranque del bot ─────
if __name__ == "__main__":
    webserver.keep_alive()
    bot.run(DISCORD_TOKEN)
