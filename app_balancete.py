import streamlit as st
import pandas as pd
import json
import time
from datetime import datetime
from fpdf import FPDF
from supabase import create_client, Client

# ==============================================================================
# CONFIGURAÇÕES E INICIALIZAÇÃO SUPABASE
# ==============================================================================
st.set_page_config(page_title="Balancete Paroquial", page_icon="📊", layout="wide")

SENHA_MESTRA = "Igreja123"

COMUNIDADES = [
    "Imaculada Conceição", "Nossa Senhora Aparecida", "Nossa Senhora da Penha",
    "Nossa Senhora de Fátima", "Sagrada Família", "Sant'Ana",
    "Santa Luzia (Fazenda Velha)", "Santa Luzia (Joacima)", "São Brás",
    "São Francisco de Paula", "São José Operário", "São Pedro", "São Sebastião"
]

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", 
         "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

def format_brl(val):
    return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# Inicializa o cliente do Supabase
@st.cache_resource
def init_connection() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# ==============================================================================
# FUNÇÕES DE ESTADO E PERSISTÊNCIA (SUPABASE)
# ==============================================================================
def obter_saldo_final_mes_anterior(comunidade, mes_atual, ano_atual):
    idx = MESES.index(mes_atual)
    
    if idx == 0:
        mes_ant = MESES[11]
        ano_ant = ano_atual - 1
    else:
        mes_ant = MESES[idx - 1]
        ano_ant = ano_atual
        
    id_ant = f"{comunidade}_{mes_ant}_{ano_ant}"
    
    # Busca o saldo inicial do mês anterior
    response_bal = supabase.table('balancetes').select('saldo_anterior').eq('id', id_ant).execute()
    
    if not response_bal.data:
        return 0.0
        
    saldo_ant = response_bal.data[0]['saldo_anterior']
    
    # Busca e soma as receitas e despesas
    response_itens = supabase.table('itens_balancete').select('tipo, valor').eq('id_balancete', id_ant).execute()
    
    tot_rec = sum(item['valor'] for item in response_itens.data if item['tipo'] == 'Receita')
    tot_desp = sum(item['valor'] for item in response_itens.data if item['tipo'] == 'Despesa')
    
    return saldo_ant + tot_rec - tot_desp

def carregar_dados_balancete(id_balancete, comunidade, mes, ano):
    response_bal = supabase.table('balancetes').select('*').eq('id', id_balancete).execute()
    dados_bal = response_bal.data
    
    if dados_bal:
        b = dados_bal[0]
        st.session_state['saldo_anterior'] = b['saldo_anterior']
        st.session_state['conta_corrente'] = b['conta_corrente']
        st.session_state['conta_poupanca'] = b['conta_poupanca']
        st.session_state['aplicacao'] = b['aplicacao']
        st.session_state['usa_corrente'] = b['usa_corrente']
        st.session_state['usa_poupanca'] = b['usa_poupanca']
        st.session_state['usa_aplicacao'] = b['usa_aplicacao']
        st.session_state['informar_saldo_anterior'] = b['informar_saldo_anterior']
        
        response_itens = supabase.table('itens_balancete').select('tipo, descricao, valor').eq('id_balancete', id_balancete).execute()
        dados_itens = response_itens.data
        
        if dados_itens:
            df_itens = pd.DataFrame(dados_itens)
            df_rec = df_itens[df_itens['tipo'] == 'Receita'][['descricao', 'valor']].rename(columns={'descricao': 'Descrição', 'valor': 'Valor'})
            df_desp = df_itens[df_itens['tipo'] == 'Despesa'][['descricao', 'valor']].rename(columns={'descricao': 'Descrição', 'valor': 'Valor'})
        else:
            df_rec = pd.DataFrame(columns=['Descrição', 'Valor'])
            df_desp = pd.DataFrame(columns=['Descrição', 'Valor'])
    else:
        st.session_state['saldo_anterior'] = obter_saldo_final_mes_anterior(comunidade, mes, ano)
        st.session_state['conta_corrente'] = 0.0
        st.session_state['conta_poupanca'] = 0.0
        st.session_state['aplicacao'] = 0.0
        st.session_state['usa_corrente'] = False
        st.session_state['usa_poupanca'] = False
        st.session_state['usa_aplicacao'] = False
        st.session_state['informar_saldo_anterior'] = False
        
        df_rec = pd.DataFrame([{"Descrição": "Dízimo", "Valor": 0.0}, {"Descrição": "Ofertas", "Valor": 0.0}])
        df_desp = pd.DataFrame([{"Descrição": "Repasse para Paróquia/Diocese 55%", "Valor": 0.0}])
        
    st.session_state['receitas_df'] = df_rec.reset_index(drop=True)
    st.session_state['despesas_df'] = df_desp.reset_index(drop=True)

def salvar_dados_balancete(id_balancete, comunidade, mes, ano, receitas_df, despesas_df):
    # Insere ou atualiza (Upsert) as configurações principais
    dados_balancete = {
        "id": id_balancete,
        "comunidade": comunidade,
        "mes": mes,
        "ano": ano,
        "saldo_anterior": st.session_state['saldo_anterior'],
        "conta_corrente": st.session_state['conta_corrente'],
        "conta_poupanca": st.session_state['conta_poupanca'],
        "aplicacao": st.session_state['aplicacao'],
        "usa_corrente": st.session_state['usa_corrente'],
        "usa_poupanca": st.session_state['usa_poupanca'],
        "usa_aplicacao": st.session_state['usa_aplicacao'],
        "informar_saldo_anterior": st.session_state['informar_saldo_anterior']
    }
    
    supabase.table('balancetes').upsert(dados_balancete).execute()
    
    # Exclui itens antigos e insere os novos
    supabase.table('itens_balancete').delete().eq('id_balancete', id_balancete).execute()
    
    itens = []
    for _, row in receitas_df.iterrows():
        if row['Descrição'] and pd.notna(row['Descrição']):
            itens.append({"id_balancete": id_balancete, "tipo": "Receita", "descricao": row['Descrição'], "valor": row.get('Valor', 0.0)})
            
    for _, row in despesas_df.iterrows():
        if row['Descrição'] and pd.notna(row['Descrição']):
            itens.append({"id_balancete": id_balancete, "tipo": "Despesa", "descricao": row['Descrição'], "valor": row.get('Valor', 0.0)})
            
    if itens:
        supabase.table('itens_balancete').insert(itens).execute()
        
    st.success("✅ Balancete salvo com sucesso na nuvem (Supabase)!")

def gerar_pdf_balancete(comunidade, mes, ano, receitas_df, despesas_df, saldo_ant, total_rec, total_desp, saldo_fin, saldos_bancos):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    # Definição de Cores
    cinza_claro = (240, 240, 240)
    cinza_medio = (210, 210, 210)
    cinza_escuro = (100, 100, 100)
    preto = (0, 0, 0)
    
    # 1. CABEÇALHO
    # Título Principal (Paróquia)
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 8, "Paróquia Sagrado Coração de Jesus - Itaipava/ES", ln=True, align='C')
    
    # Subtítulo 1 (Comunidade - um pouco menor)
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 8, f"Comunidade {comunidade}", ln=True, align='C')
    
    # Subtítulo 2 (Balancete e Data)
    pdf.set_font("Arial", "I", 11)
    pdf.set_text_color(*cinza_escuro)
    pdf.cell(0, 6, f"Balancete Mensal de Prestação de Contas | {mes.capitalize()}/{ano}", ln=True, align='C')
    pdf.set_text_color(*preto)
    pdf.ln(8)
        
    # 2. SALDO ANTERIOR (Destaque Topo)
    pdf.set_fill_color(*cinza_claro)
    pdf.set_font("Arial", "B", 10)
    # Largura total = 190 (150 para texto + 40 para valor)
    pdf.cell(150, 8, " SALDO ANTERIOR", border=0, fill=True)
    pdf.cell(40, 8, format_brl(saldo_ant), border=0, fill=True, align='R', ln=True)
    pdf.ln(6)
    
    # 3. ENTRADAS
    pdf.set_font("Arial", "B", 10)
    pdf.cell(150, 8, " ENTRADAS", border='B')
    pdf.cell(40, 8, "", border='B', ln=True) 
    
    pdf.set_font("Arial", "", 9)
    for idx, r in receitas_df.iterrows():
        if r['Descrição']:
            # Recuo de 15 pontos. Largura restante: 135 (texto) + 40 (valor) = 190.
            pdf.set_x(15) 
            pdf.cell(135, 7, f" {idx+1}. {r['Descrição']}", border='B')
            pdf.cell(40, 7, format_brl(r['Valor']), border='B', ln=True, align='R')
            
    pdf.set_font("Arial", "B", 9)
    pdf.set_x(15)
    pdf.cell(135, 8, " TOTAL DE ENTRADAS", border=0)
    pdf.cell(40, 8, format_brl(total_rec), border=0, ln=True, align='R')
    pdf.ln(6)
    
    # 4. SAÍDAS (DESEMBOLSOS)
    pdf.set_font("Arial", "B", 10)
    pdf.set_x(10)
    pdf.cell(150, 8, " SAÍDAS (DESEMBOLSOS)", border='B')
    pdf.cell(40, 8, "", border='B', ln=True)
    
    pdf.set_font("Arial", "", 9)
    for idx, d in despesas_df.iterrows():
        if d['Descrição']:
            pdf.set_x(15)
            txt_desp = d['Descrição'][:80] 
            pdf.cell(135, 7, f" {idx+1}. {txt_desp}", border='B')
            pdf.cell(40, 7, format_brl(d['Valor']), border='B', ln=True, align='R')
            
    pdf.set_font("Arial", "B", 9)
    pdf.set_x(15)
    pdf.cell(135, 8, " TOTAL DE SAÍDAS", border=0)
    pdf.cell(40, 8, format_brl(total_desp), border=0, ln=True, align='R')
    pdf.ln(12)
    
    # 5. RESUMO DO MOVIMENTO (Substituindo o antigo Saldo Bruto)
    margem_esq = 35 
    largura_resumo = 140
    
    pdf.set_x(margem_esq)
    pdf.set_fill_color(*cinza_medio) 
    pdf.set_font("Arial", "B", 9)
    pdf.cell(largura_resumo, 7, "RESUMO DO MOVIMENTO DO MÊS", border=0, fill=True, align='C', ln=True)
    
    pdf.set_font("Arial", "", 9)
    pdf.set_x(margem_esq)
    pdf.cell(100, 7, " Entradas do Mês", border='B')
    pdf.cell(40, 7, format_brl(total_rec), border='B', align='R', ln=True)
    
    pdf.set_x(margem_esq)
    pdf.cell(100, 7, " Saídas do Mês", border='B')
    pdf.cell(40, 7, f"({format_brl(total_desp)})", border='B', align='R', ln=True)
    
    pdf.set_x(margem_esq)
    pdf.set_fill_color(*cinza_claro)
    pdf.set_font("Arial", "B", 9)
    # Aqui o Saldo Final assume o seu lugar correto (Anterior + Entradas - Saídas)
    pdf.cell(100, 7, " SALDO FINAL", border=0, fill=True)
    pdf.cell(40, 7, format_brl(saldo_fin), border=0, fill=True, align='R', ln=True)
    
    pdf.ln(10)
    
    # 6. COMPOSIÇÃO DO SALDO PATRIMONIAL
    pdf.set_x(margem_esq)
    pdf.set_font("Arial", "B", 9)
    pdf.cell(largura_resumo, 7, "COMPOSIÇÃO DO SALDO PATRIMONIAL", border=0, ln=True)
    
    pdf.set_font("Arial", "", 9)
    for desc_banco, val_banco in saldos_bancos.items():
        pdf.set_x(margem_esq)
        pdf.cell(100, 7, f" {desc_banco.upper()}", border='B')
        pdf.cell(40, 7, format_brl(val_banco), border='B', align='R', ln=True)
        
    # 7. ASSINATURAS
    if pdf.get_y() > 240: 
        pdf.add_page()
    else:
        pdf.ln(25)
        
    y_sign = pdf.get_y()
    pdf.line(30, y_sign, 85, y_sign)
    pdf.set_xy(30, y_sign + 1)
    pdf.set_font("Arial", "", 9)
    pdf.cell(55, 5, "Tesoureiro(a)", align='C')
    
    pdf.line(120, y_sign, 175, y_sign)
    pdf.set_xy(120, y_sign + 1)
    # Assinatura corrigida
    pdf.cell(55, 5, "Coordenador(a) do CPC", align='C')
    
    return pdf.output()

# 2. Modal de Exclusão
@st.dialog("🗑️ Confirmar Exclusão")
def modal_excluir(id_balancete):
    st.warning("Tem certeza que deseja excluir todos os registros deste balancete? A ação não pode ser desfeita.")
    senha = st.text_input("Senha Mestra", type="password")
    
    if st.button("Confirmar Exclusão", type="primary", use_container_width=True):
        if senha == SENHA_MESTRA:
            # A exclusão no balancetes via Supabase deleta os itens também devido ao ON DELETE CASCADE configurado no SQL
            supabase.table('balancetes').delete().eq('id', id_balancete).execute()
            
            st.success("Balancete excluído da nuvem.")
            st.session_state['id_atual'] = None
            time.sleep(1)
            st.rerun()
        else:
            st.error("Senha incorreta.")

# ==============================================================================
# INTERFACE DO USUÁRIO
# ==============================================================================
st.title("📑 Balancete Comunitário")

hoje = datetime.now()
ano_atual = hoje.year
mes_atual_idx = hoje.month - 1

col_com, col_mes, col_ano = st.columns([2, 1, 1])

# Adicionamos index=None e um placeholder
comunidade_sel = col_com.selectbox("Comunidade", COMUNIDADES, index=None, placeholder="Selecione...")
mes_sel = col_mes.selectbox("Mês", MESES, index=mes_atual_idx)
ano_sel = col_ano.number_input("Ano", min_value=2020, max_value=2050, value=ano_atual, step=1)

st.divider()

# Tudo abaixo só será exibido se uma comunidade for selecionada
if comunidade_sel:
    id_atual = f"{comunidade_sel}_{mes_sel}_{ano_sel}"

    if st.session_state.get('id_atual') != id_atual:
        carregar_dados_balancete(id_atual, comunidade_sel, mes_sel, ano_sel)
        st.session_state['id_atual'] = id_atual

    # ==============================================================================
    # IMPORTAÇÃO DE JSON
    # ==============================================================================
    with st.expander("📥 Importar Dados do Sistema de Tesouraria (JSON)", expanded=False):
        arquivo_json = st.file_uploader("Envie o arquivo JSON gerado no outro sistema", type=['json'])
        if arquivo_json is not None:
            dados = json.load(arquivo_json)
            if str(dados.get("comunidade", "")).upper() != str(comunidade_sel).upper() or \
                str(dados.get("mes", "")).upper() != str(mes_sel).upper() or \
                int(dados.get("ano", 0)) != int(ano_sel):
                st.error(f"⚠️ O arquivo selecionado pertence a {dados.get('comunidade')} - {dados.get('mes')}/{dados.get('ano')}. Mude os filtros se quiser importar estes dados.")
            else:
                if st.button("Aplicar Dados do JSON", type="primary"):
                    lancamentos = dados.get("lancamentos", [])
                    
                    v_dizimo = sum(l['valor'] for l in lancamentos if l['tipo'] == 'Receita' and l['categoria'] == 'Dízimo')
                    v_ofertas = sum(l['valor'] for l in lancamentos if l['tipo'] == 'Receita' and l['categoria'] == 'Ofertas')
                    v_rendimentos = sum(l['valor'] for l in lancamentos if l['tipo'] == 'Receita' and l['categoria'] == 'Receitas Financeiras')
                    v_repasse = sum(l['valor'] for l in lancamentos if l['tipo'] == 'Despesa' and 'Repasse' in l['categoria'])
                    outras_despesas = [{"Descrição": l['descricao'], "Valor": l['valor']} for l in lancamentos if l['tipo'] == 'Despesa' and 'Repasse' not in l['categoria']]
                    
                    novas_receitas = [
                        {"Descrição": "Dízimo", "Valor": v_dizimo},
                        {"Descrição": "Ofertas", "Valor": v_ofertas}
                    ]
                    if v_rendimentos > 0 or st.session_state['usa_poupanca'] or st.session_state['usa_aplicacao']:
                        novas_receitas.append({"Descrição": "Rendimentos Bancários", "Valor": v_rendimentos})
                        
                    novas_despesas = [{"Descrição": "Repasse para Paróquia/Diocese 55%", "Valor": v_repasse}]
                    novas_despesas.extend(outras_despesas)
                    
                    st.session_state['receitas_df'] = pd.DataFrame(novas_receitas)
                    st.session_state['despesas_df'] = pd.DataFrame(novas_despesas)
                    st.success("Dados aplicados na tabela com sucesso!")
                    st.rerun()

    # ==============================================================================
    # OPÇÕES DO BALANCETE
    # ==============================================================================
    st.markdown("### ⚙️ Opções do Balancete")
    c_opt1, c_opt2, c_opt3, c_opt4 = st.columns(4)
    st.session_state['informar_saldo_anterior'] = c_opt1.toggle("Saldo Anterior", value=st.session_state.get('informar_saldo_anterior', False))
    st.session_state['usa_corrente'] = c_opt2.toggle("Conta Corrente", value=st.session_state.get('usa_corrente', False))
    st.session_state['usa_poupanca'] = c_opt3.toggle("Conta Poupança", value=st.session_state.get('usa_poupanca', False))
    st.session_state['usa_aplicacao'] = c_opt4.toggle("Conta Aplicação", value=st.session_state.get('usa_aplicacao', False))

    if st.session_state['usa_poupanca'] or st.session_state['usa_aplicacao']:
        if not st.session_state['receitas_df'].empty and "Rendimentos Bancários" not in st.session_state['receitas_df']['Descrição'].values:
            st.session_state['receitas_df'] = pd.concat([st.session_state['receitas_df'], pd.DataFrame([{"Descrição": "Rendimentos Bancários", "Valor": 0.0}])], ignore_index=True)

    st.divider()

    # ==============================================================================
    # TABELAS
    # ==============================================================================
    col_rec, col_desp = st.columns(2)

    with col_rec:
        st.markdown("#### 📥 Entradas")
        receitas_edit = st.data_editor(
            st.session_state['receitas_df'], num_rows="dynamic", use_container_width=True, key="edit_receitas",
            column_config={"Descrição": st.column_config.TextColumn("Descrição", required=True), "Valor": st.column_config.NumberColumn("Valor (R$)", format="R$ %.2f", min_value=0.0)}
        )
        total_receitas = receitas_edit['Valor'].sum()
        st.markdown(f"<div style='text-align: right; font-weight: bold; color: green;'>Total Entradas: R$ {total_receitas:,.2f}</div>", unsafe_allow_html=True)

    with col_desp:
        st.markdown("#### 📤 Saídas")
        despesas_edit = st.data_editor(
            st.session_state['despesas_df'], num_rows="dynamic", use_container_width=True, key="edit_despesas",
            column_config={"Descrição": st.column_config.TextColumn("Descrição", required=True), "Valor": st.column_config.NumberColumn("Valor (R$)", format="R$ %.2f", min_value=0.0)}
        )
        total_despesas = despesas_edit['Valor'].sum()
        st.markdown(f"<div style='text-align: right; font-weight: bold; color: red;'>Total Saídas: R$ {total_despesas:,.2f}</div>", unsafe_allow_html=True)

    st.divider()

    # ==============================================================================
    # TOTALIZADOR E CAIXA
    # ==============================================================================
    col_res, col_bancos = st.columns(2)

    with col_res:
        st.markdown("### 📊 Totalizador")
        if st.session_state['informar_saldo_anterior']:
            st.session_state['saldo_anterior'] = st.number_input("Saldo Anterior (R$)", value=st.session_state['saldo_anterior'], step=10.0)
        else:
            st.markdown(f"**Saldo Anterior:** R$ {st.session_state['saldo_anterior']:,.2f}")
        
        saldo_final = st.session_state['saldo_anterior'] + total_receitas - total_despesas
        st.markdown(f"**(+) Entradas:** R$ {total_receitas:,.2f}")
        st.markdown(f"**(-) Saídas:** R$ {total_despesas:,.2f}")
        st.markdown(f"#### Saldo Final: <span style='color: {'#2e7d32' if saldo_final >= 0 else '#d32f2f'};'>R$ {saldo_final:,.2f}</span>", unsafe_allow_html=True)

    with col_bancos:
        st.markdown("### 🏦 Patrimônio")
        total_bancos = 0.0
        saldos_bancos_dict = {}
        
        if st.session_state['usa_corrente']:
            st.session_state['conta_corrente'] = st.number_input("Conta Corrente (R$)", value=st.session_state['conta_corrente'], step=10.0)
            total_bancos += st.session_state['conta_corrente']
            saldos_bancos_dict["Conta Corrente"] = st.session_state['conta_corrente']
        else:
            st.session_state['conta_corrente'] = 0.0

        if st.session_state['usa_poupanca']:
            st.session_state['conta_poupanca'] = st.number_input("Conta Poupança (R$)", value=st.session_state['conta_poupanca'], step=10.0)
            total_bancos += st.session_state['conta_poupanca']
            saldos_bancos_dict["Conta Poupança"] = st.session_state['conta_poupanca']
        else:
            st.session_state['conta_poupanca'] = 0.0

        if st.session_state['usa_aplicacao']:
            st.session_state['aplicacao'] = st.number_input("Aplicação (R$)", value=st.session_state['aplicacao'], step=10.0)
            total_bancos += st.session_state['aplicacao']
            saldos_bancos_dict["Aplicação"] = st.session_state['aplicacao']
        else:
            st.session_state['aplicacao'] = 0.0
            
        saldo_caixa = saldo_final - total_bancos
        saldos_bancos_dict["Caixa (Espécie)"] = saldo_caixa
        
        cor_caixa = "#2e7d32" if saldo_caixa >= 0 else "#d32f2f"
        st.markdown(f"#### Caixa (Espécie): <span style='color: {cor_caixa};'>R$ {saldo_caixa:,.2f}</span>", unsafe_allow_html=True)

    # ==============================================================================
    # BOTÕES DE AÇÃO (SALVAR, EXCLUIR, PDF)
    # ==============================================================================
    st.write("")
    c_btn1, c_btn2, c_btn3 = st.columns(3)

    with c_btn1:
        if st.button("💾 Salvar", type="primary", use_container_width=True):
            st.session_state['receitas_df'] = receitas_edit
            st.session_state['despesas_df'] = despesas_edit
            salvar_dados_balancete(id_atual, comunidade_sel, mes_sel, ano_sel, receitas_edit, despesas_edit)

    with c_btn2:
        if st.button("🗑️ Excluir", use_container_width=True):
            modal_excluir(id_atual)

    with c_btn3:
        pdf_bytes = gerar_pdf_balancete(
            comunidade_sel, mes_sel, ano_sel, 
            receitas_edit, despesas_edit, 
            st.session_state['saldo_anterior'], 
            total_receitas, total_despesas, 
            saldo_final, saldos_bancos_dict
        )
        
        st.download_button(
            label="📄 Gerar PDF",
            data=bytes(pdf_bytes),
            file_name=f"Balancete_{comunidade_sel}_{mes_sel}_{ano_sel}.pdf",
            mime="application/pdf",
            use_container_width=True
        )

else:
    # Mensagem exibida enquanto nenhuma comunidade for selecionada
    st.info("👆 Por favor, selecione uma Comunidade acima para iniciar ou editar um balancete.")
