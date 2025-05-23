import flask
from flask import Flask, request, jsonify
from flask_cors import CORS
import joblib
import pandas as pd
import numpy as np
from datetime import datetime
import locale
from geopy.geocoders import Nominatim 
import requests
import uuid # Para gerar IDs únicos para cada previsão
import mysql.connector # Importa o conector MySQL
from mysql.connector import errorcode # Para tratar erros específicos do MySQL

# --- 1. Configurações Iniciais e Inicialização do Flask ---
app = Flask(__name__)
CORS(app)

# Configuração do locale
try:
    locale.setlocale(locale.LC_TIME, 'pt_BR.UTF8')
except locale.Error:
    print("AVISO: Não foi possível configurar o locale 'pt_BR.UTF8'.")
    try:
        locale.setlocale(locale.LC_TIME, 'Portuguese_Brazil')
    except locale.Error:
        print("AVISO: Não foi possível configurar o locale 'Portuguese_Brazil'.")

# --- 2. Constantes e Inicializadores Globais ---
HERE_API_KEY = "zK9f9fu8wVtDG9dCY4fUvfpO6K4LDdRYtQupwo89fQ4" 
HERE_ROUTING_URL = "https://router.hereapi.com/v8/routes"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"

# User-Agent para Nominatim
# !!!!! ATUALIZE COM SEU EMAIL OU UM IDENTIFICADOR ÚNICO PARA SUA APLICAÇÃO !!!!!
NOMINATIM_USER_AGENT = "ComparadriveApp/1.0 (fernando-97js@outlook.com)" # Verifique/Atualize este email
geolocator = Nominatim(user_agent=NOMINATIM_USER_AGENT)

# --- Configurações do MySQL ---
# !!!!! ATUALIZE COM SUAS CREDENCIAIS REAIS SE FOREM DIFERENTES !!!!!
MYSQL_CONFIG = {
    'host': 'localhost',      # Geralmente 'localhost' para um servidor local
    'user': 'fernando',       # Seu usuário MySQL
    'password': '28Do06De1997@', # Sua senha MySQL
    'database': 'comparadrive',  # O nome do banco de dados que você criou
    'auth_plugin': 'mysql_native_password' # <<< ADICIONADO PARA FORÇAR O PLUGIN
}
MYSQL_TABLE_NAME = "previsoes_viagens" # Nome da tabela que será criada

# --- 3. Funções do Banco de Dados MySQL ---
def get_mysql_connection():
    """Cria e retorna uma conexão com o banco de dados MySQL."""
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        app.logger.debug("Conexão com MySQL estabelecida.")
        return conn
    except mysql.connector.Error as err:
        app.logger.error(f"Erro ao conectar ao MySQL: {err}", exc_info=True)
        return None 

def init_mysql_db():
    """Cria a tabela de previsões no MySQL se ela não existir."""
    conn = get_mysql_connection()
    if not conn:
        app.logger.error("Não foi possível conectar ao MySQL para inicializar a tabela.")
        print(f"ALERTA: FALHA AO CONECTAR AO MYSQL PARA INICIALIZAR TABELA '{MYSQL_TABLE_NAME}'.")
        return

    try:
        cursor = conn.cursor()
        app.logger.info(f"Verificando/Criando tabela '{MYSQL_TABLE_NAME}' no banco '{MYSQL_CONFIG['database']}'...")
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {MYSQL_TABLE_NAME} (
                id INT AUTO_INCREMENT PRIMARY KEY,
                timestamp_previsao DATETIME NOT NULL,
                ride_id_gerado VARCHAR(36) UNIQUE NOT NULL, 
                endereco_origem_input TEXT,
                endereco_destino_input TEXT,
                categoria_produto VARCHAR(255),
                preco_estimado_modelo DECIMAL(10, 2),
                tempo_viagem_estimado_api DECIMAL(10, 2),
                dia_semana_previsao VARCHAR(50),
                distancia_estimada_api DECIMAL(10, 2),
                coordenadas_origem VARCHAR(255),
                coordenadas_destino VARCHAR(255),
                h_inicio_min_previsao INT,
                h_fim_min_previsao INT,
                duracao_viagem_min_previsao DECIMAL(10, 2),
                delta_lat_calculado DECIMAL(10, 7),
                delta_lon_calculado DECIMAL(10, 7)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        conn.commit()
        app.logger.info(f"Tabela '{MYSQL_TABLE_NAME}' verificada/criada com sucesso no MySQL.")
    except mysql.connector.Error as err:
        app.logger.error(f"Erro ao criar tabela '{MYSQL_TABLE_NAME}' no MySQL: {err}", exc_info=True)
        print(f"ALERTA: FALHA AO CRIAR TABELA '{MYSQL_TABLE_NAME}' NO MYSQL: {err}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()
            app.logger.debug("Conexão com MySQL fechada após init_mysql_db.")

def salvar_previsao_no_mysql_db(dados_previsao):
    """Salva uma nova previsão no banco de dados MySQL. Retorna True em sucesso, False em falha."""
    sql = f''' INSERT INTO {MYSQL_TABLE_NAME} (
                timestamp_previsao, ride_id_gerado, endereco_origem_input, endereco_destino_input,
                categoria_produto, preco_estimado_modelo, tempo_viagem_estimado_api,
                dia_semana_previsao, distancia_estimada_api, coordenadas_origem,
                coordenadas_destino, h_inicio_min_previsao, h_fim_min_previsao,
                duracao_viagem_min_previsao, delta_lat_calculado, delta_lon_calculado
              ) VALUES (%(timestamp_previsao)s, %(ride_id_gerado)s, %(endereco_origem_input)s, 
                        %(endereco_destino_input)s, %(categoria_produto)s, %(preco_estimado_modelo)s,
                        %(tempo_viagem_estimado_api)s, %(dia_semana_previsao)s, %(distancia_estimada_api)s,
                        %(coordenadas_origem)s, %(coordenadas_destino)s, %(h_inicio_min_previsao)s,
                        %(h_fim_min_previsao)s, %(duracao_viagem_min_previsao)s,
                        %(delta_lat_calculado)s, %(delta_lon_calculado)s) '''
    
    conn = get_mysql_connection()
    if not conn:
        app.logger.error(f"Falha ao conectar ao MySQL para salvar previsão (Ride ID: {dados_previsao.get('ride_id_gerado')}).")
        return False
    
    try:
        cursor = conn.cursor()
        params_dict = {
            'timestamp_previsao': dados_previsao.get('timestamp_previsao'),
            'ride_id_gerado': dados_previsao.get('ride_id_gerado'),
            'endereco_origem_input': dados_previsao.get('endereco_origem_input'),
            'endereco_destino_input': dados_previsao.get('endereco_destino_input'),
            'categoria_produto': dados_previsao.get('categoria_produto'),
            'preco_estimado_modelo': float(dados_previsao.get('preco_estimado_modelo', 0.0)),
            'tempo_viagem_estimado_api': float(dados_previsao.get('tempo_viagem_estimado_api', 0.0)),
            'dia_semana_previsao': dados_previsao.get('dia_semana_previsao'),
            'distancia_estimada_api': float(dados_previsao.get('distancia_estimada_api', 0.0)),
            'coordenadas_origem': dados_previsao.get('coordenadas_origem'),
            'coordenadas_destino': dados_previsao.get('coordenadas_destino'),
            'h_inicio_min_previsao': int(dados_previsao.get('h_inicio_min_previsao', 0)),
            'h_fim_min_previsao': int(dados_previsao.get('h_fim_min_previsao', 0)),
            'duracao_viagem_min_previsao': float(dados_previsao.get('duracao_viagem_min_previsao', 0.0)),
            'delta_lat_calculado': float(dados_previsao.get('delta_lat_calculado', 0.0)),
            'delta_lon_calculado': float(dados_previsao.get('delta_lon_calculado', 0.0))
        }
        cursor.execute(sql, params_dict)
        conn.commit()
        app.logger.info(f"Previsão salva no MySQL DB. Ride ID: {dados_previsao.get('ride_id_gerado')}, DB ID: {cursor.lastrowid}")
        return True
    except mysql.connector.Error as err:
        app.logger.error(f"Erro mysql.connector ao salvar previsão (Ride ID: {dados_previsao.get('ride_id_gerado')}): {err}", exc_info=True)
        if conn.is_connected(): conn.rollback()
        return False
    except Exception as e_global:
        app.logger.error(f"Erro GERAL ao salvar previsão no MySQL (Ride ID: {dados_previsao.get('ride_id_gerado')}): {e_global}", exc_info=True)
        if conn.is_connected(): conn.rollback()
        return False
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()
            app.logger.debug("Conexão com MySQL fechada após salvar_previsao_no_mysql_db.")

# --- 4. Funções Auxiliares de Negócio ---
def map_day_to_number(day_name):
    day_mapping = {
        'monday': 0, 'segunda-feira': 0, 'segunda': 0, 'tuesday': 1, 'terça-feira': 1, 'terça': 1,
        'wednesday': 2, 'quarta-feira': 2, 'quarta': 2, 'thursday': 3, 'quinta-feira': 3, 'quinta': 3,
        'friday': 4, 'sexta-feira': 4, 'sexta': 4, 'saturday': 5, 'sábado': 5, 'sunday': 6, 'domingo': 6
    }
    return day_mapping.get(str(day_name).lower(), None)

def get_coordinates(address):
    try:
        location = geolocator.geocode(address, timeout=10)
        if location: return (location.latitude, location.longitude)
        app.logger.warning(f"Endereço não encontrado (geopy): {address}")
        return None
    except Exception as e:
        app.logger.error(f"Erro ao geocodificar (geopy) '{address}': {e}", exc_info=True)
        return None

def get_route_data(origin_coords, destination_coords, api_key):
    origin_str = f"{origin_coords[0]},{origin_coords[1]}"
    destination_str = f"{destination_coords[0]},{destination_coords[1]}"
    params = {"transportMode": "car", "origin": origin_str, "destination": destination_str, "return": "summary,polyline", "apikey": api_key}
    try:
        response = requests.get(HERE_ROUTING_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data and "routes" in data and data["routes"] and "sections" in data["routes"][0] and data["routes"][0]["sections"]:
            section = data["routes"][0]["sections"][0]
            summary = section.get("summary", {})
            distancia_km = summary.get("length", 0) / 1000.0
            duracao_min = summary.get("duration", 0) / 60.0
            polyline_str = section.get("polyline")
            return (distancia_km, duracao_min, polyline_str)
        app.logger.warning(f"API HERE (rota) estrutura inesperada. Resposta: {data.get('title', data)}")
        return (None, None, None)
    except requests.exceptions.HTTPError as http_err:
        app.logger.error(f"Erro HTTP API HERE (rota): {http_err}. Resposta: {response.text if 'response' in locals() else 'N/A'}")
        return (None, None, None)
    except requests.exceptions.RequestException as req_err:
        app.logger.error(f"Erro de requisição API HERE (rota): {req_err}")
        return (None, None, None)
    except ValueError as json_err: 
        app.logger.error(f"Erro JSON API HERE (rota): {json_err}. Resposta: {response.text if 'response' in locals() else 'N/A'}")
        return (None, None, None)
    except Exception as e:
        app.logger.error(f"Erro inesperado em get_route_data: {e}", exc_info=True)
        return (None, None, None)

# --- 5. Carregar Modelo, Encoders e Lista de Features ---
MODEL_FILENAME = "modelo_treinado.joblib"; ENCODERS_FILENAME = "encoders.joblib"; FEATURES_FILENAME = "features.joblib"
model, label_encoders, expected_features_order = None, None, None
try:
    model = joblib.load(MODEL_FILENAME)
    label_encoders = joblib.load(ENCODERS_FILENAME)
    expected_features_order = joblib.load(FEATURES_FILENAME)
    app.logger.info("Modelo, encoders e features carregados.")
except FileNotFoundError as fnf_error: app.logger.error(f"Erro Crítico - Arquivo não encontrado: {fnf_error}.")
except Exception as load_error: app.logger.error(f"Erro Crítico ao carregar modelo/etc: {load_error}", exc_info=True)

# --- 6. Função Principal de Lógica de Previsão (MODIFICADA para salvar em MySQL) ---
def obter_previsao_viagem(dados_entrada_api):
    try:
        app.logger.debug(f"obter_previsao_viagem chamada com: {dados_entrada_api}")
        endereco_origem_input = dados_entrada_api.get("endereco_origem")
        endereco_destino_input = dados_entrada_api.get("endereco_destino")
        categoria_produto_input = dados_entrada_api.get("categoria")

        if not all([endereco_origem_input, endereco_destino_input, categoria_produto_input]):
             return {"error": "Campos de entrada ausentes (origem, destino ou categoria)."}, 400

        categoria_para_modelo_str = None
        if not label_encoders or "ProductID" not in label_encoders or label_encoders.get("ProductID") is None:
            app.logger.error("LabelEncoder para 'ProductID' não carregado ou ausente. Verifique 'encoders.joblib'.")
            return {"error": "Erro de configuração do servidor (encoder ProductID)."}, 500
        
        categorias_validas_map = {str(cat).lower(): str(cat) for cat in label_encoders["ProductID"].classes_}
        if categoria_produto_input.lower() in categorias_validas_map:
            categoria_para_modelo_str = categorias_validas_map[categoria_produto_input.lower()]
        else:
            return {"error": f"Categoria '{categoria_produto_input}' inválida. Válidas: {', '.join(label_encoders['ProductID'].classes_)}"}, 400

        coords_origem = get_coordinates(endereco_origem_input)
        if not coords_origem: return {"error": f"Não foi possível geocodificar origem: '{endereco_origem_input}'"}, 400
        coords_destino = get_coordinates(endereco_destino_input)
        if not coords_destino: return {"error": f"Não foi possível geocodificar destino: '{endereco_destino_input}'"}, 400
        lat_origem, lon_origem = coords_origem
        lat_destino, lon_destino = coords_destino

        distancia_api, duracao_api, route_polyline_here = get_route_data(coords_origem, coords_destino, HERE_API_KEY)
        if distancia_api is None: 
            return {"error": "Não foi possível obter dados de rota da API HERE (distância/duração)."}, 500

        now = datetime.now()
        dia_numero_modelo = now.weekday()
        h_inicio_min_modelo = now.hour * 60 + now.minute
        h_fim_min_modelo = h_inicio_min_modelo + duracao_api 
        dias_semana_pt = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
        dia_semana_nome_display = dias_semana_pt[dia_numero_modelo]
        delta_lat_modelo = lat_destino - lat_origem
        delta_lon_modelo = lon_destino - lon_origem

        dados_para_modelo_df_dict = {
            "ProductID": categoria_para_modelo_str, "Dia_Numero": dia_numero_modelo,
            "Tempo_Viagem_Min": duracao_api, "Distância_km": distancia_api,
            "Delta_Lat": delta_lat_modelo, "Delta_Lon": delta_lon_modelo,
            "H_Inicio_Min": h_inicio_min_modelo, "H_Fim_Min": int(h_fim_min_modelo),
            "Duração_Viagem": duracao_api 
        }
        df_para_predict = pd.DataFrame([dados_para_modelo_df_dict])

        if "ProductID" in label_encoders and label_encoders.get("ProductID") is not None:
            try:
                df_para_predict["ProductID"] = label_encoders["ProductID"].transform(df_para_predict["ProductID"])
            except ValueError as e:
                app.logger.error(f"Erro ao transformar ProductID '{categoria_para_modelo_str}' com encoder: {e}")
                return {"error": f"Valor de categoria '{categoria_para_modelo_str}' não reconhecido pelo encoder."}, 400
        
        if not model or not expected_features_order:
             app.logger.error("Modelo ou expected_features_order não carregados.")
             return {"error": "Erro de configuração do servidor (modelo/features)."}, 500
        
        try:
            X_para_predict = df_para_predict[expected_features_order]
        except KeyError as e:
            app.logger.error(f"Features ausentes. Esperadas: {expected_features_order}. No DF: {list(df_para_predict.columns)}. Erro: {e}")
            return {"error": "Erro ao preparar features para o modelo (features ausentes)."}, 500
            
        preco_estimado_pelo_modelo = model.predict(X_para_predict)[0]
        
        # --- PREPARAR DADOS PARA SALVAR NO BANCO DE DADOS MYSQL ---
        dados_para_salvar_db = {
            'timestamp_previsao': now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3], 
            'ride_id_gerado': str(uuid.uuid4()),
            'endereco_origem_input': endereco_origem_input,
            'endereco_destino_input': endereco_destino_input,
            'categoria_produto': categoria_produto_input,
            'preco_estimado_modelo': float(round(preco_estimado_pelo_modelo, 2)),
            'tempo_viagem_estimado_api': float(round(duracao_api, 2)),
            'dia_semana_previsao': dia_semana_nome_display,
            'distancia_estimada_api': float(round(distancia_api, 2)),
            'coordenadas_origem': f"{lat_origem:.7f},{lon_origem:.7f}",
            'coordenadas_destino': f"{lat_destino:.7f},{lon_destino:.7f}",
            'h_inicio_min_previsao': int(h_inicio_min_modelo),
            'h_fim_min_previsao': int(h_fim_min_modelo),
            'duracao_viagem_min_previsao': float(round(duracao_api, 2)),
            'delta_lat_calculado': float(round(delta_lat_modelo, 7)),
            'delta_lon_calculado': float(round(delta_lon_modelo, 7))
        }
        
        # Tenta salvar no DB, mas não deixa isso quebrar a resposta principal
        if not salvar_previsao_no_mysql_db(dados_para_salvar_db):
            app.logger.warning(f"Falha ao salvar a previsão (Ride ID: {dados_para_salvar_db['ride_id_gerado']}) no banco de dados MySQL, mas a resposta da API será enviada.")
        
        # --- PREPARAR DADOS PARA RETORNAR AO FRONTEND ---
        dados_retorno_frontend = {
            "predicted_price": float(round(preco_estimado_pelo_modelo, 2)), 
            "endereco_origem": endereco_origem_input, 
            "endereco_destino": endereco_destino_input, 
            "categoria_viagem": categoria_produto_input,
            "distancia_km": float(round(distancia_api, 2)), 
            "duracao_min": float(round(duracao_api, 1)),
            "hora_solicitacao": now.strftime('%H:%M:%S'), 
            "dia_solicitacao": dia_semana_nome_display,
            "route_polyline": route_polyline_here, 
            "origin_coords": {"lat": float(lat_origem), "lng": float(lon_origem)}, 
            "destination_coords": {"lat": float(lat_destino), "lng": float(lon_destino)} 
        }
        return dados_retorno_frontend, 200

    except Exception as e_geral: 
        app.logger.error(f"Erro GERAL INESPERADO na função obter_previsao_viagem: {e_geral}", exc_info=True)
        return {"error": "Ocorreu um erro interno muito grave no servidor durante a previsão."}, 500

# --- 7. Rota Principal de Previsão ---
@app.route('/api/predict', methods=['POST'])
def rota_de_previsao():
    if not all([model, label_encoders, expected_features_order]):
        app.logger.error("Tentativa de previsão com modelo/encoders/features não carregados.")
        return jsonify({"error": "Serviço temporariamente indisponível (configuração do modelo incompleta)."}), 503
    try:
        dados_json_recebidos = request.get_json()
        if not dados_json_recebidos: return jsonify({"error": "Requisição vazia ou não é JSON."}), 400
    except Exception as e:
        app.logger.error(f"Erro ao parsear JSON da requisição: {e}")
        return jsonify({"error": f"JSON malformado: {str(e)}"}), 400

    campos_obrigatorios = ['endereco_origem', 'endereco_destino', 'categoria']
    campos_ausentes = [campo for campo in campos_obrigatorios if campo not in dados_json_recebidos]
    if campos_ausentes: return jsonify({"error": f"Campos obrigatórios ausentes: {', '.join(campos_ausentes)}"}), 400

    resultado, status_code = obter_previsao_viagem(dados_json_recebidos)
    return jsonify(resultado), status_code

# --- 8. ROTA PARA SUGESTÕES DE ENDEREÇO USANDO NOMINATIM ---
@app.route('/api/nominatim-suggest', methods=['GET'])
def nominatim_suggest():
    query = request.args.get('q')
    if not query: return jsonify({"error": "Parâmetro 'q' (query) é obrigatório"}), 400
    headers = { 'User-Agent': NOMINATIM_USER_AGENT }
    params = {
        'q': query, 'format': 'json', 'addressdetails': 1,
        'limit': 5, 'accept-language': 'pt-BR,pt;q=0.9'
    }
    try:
        response = requests.get(NOMINATIM_SEARCH_URL, params=params, headers=headers, timeout=7)
        response.raise_for_status()
        return jsonify(response.json()) 
    except requests.exceptions.Timeout:
        app.logger.error("Timeout API Nominatim.")
        return jsonify({"error": "Timeout (Nominatim)."}), 504
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Erro API Nominatim: {e}")
        return jsonify({"error": "Erro (Nominatim)."}), 502
    except ValueError as json_err: 
        app.logger.error(f"Erro JSON API Nominatim: {json_err}. Resposta: {response.text if 'response' in locals() else 'N/A'}")
        return jsonify({"error": "Resposta inválida do serviço de sugestão."}), 502
    except Exception as e:
        app.logger.error(f"Erro inesperado em nominatim_suggest: {e}", exc_info=True)
        return jsonify({"error": "Erro interno (Nominatim suggest)."}), 500

# --- Inicializa o Banco de Dados e Roda o Servidor Flask ---
if __name__ == '__main__':
    try:
        init_mysql_db() # Chama a função para criar a tabela MySQL se não existir
    except Exception as e:
        print(f"ALERTA: FALHA CRÍTICA ao inicializar o banco de dados MySQL durante o startup: {e}")
    app.run(host='0.0.0.0', port=5000, debug=True)
