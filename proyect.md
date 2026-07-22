La tesis central sería:

Conecta las fuentes una vez, descubre el lenguaje de la empresa, verifica ese lenguaje y expón un contexto gobernado a todos los agentes.

1. Qué estás construyendo realmente

Conviene separar cinco artefactos que normalmente se mezclan:

Artefacto	Función
Glosario	Términos, definiciones, sinónimos, acrónimos, traducciones y propietarios.
Ontología	Conceptos, tipos, relaciones, jerarquías, restricciones y reglas.
Mappings semánticos	Indican qué tabla, columna, API, campo o documento representa cada concepto.
Knowledge graph	Instancias y hechos: clientes concretos, cuentas concretas, vuelos concretos y relaciones entre ellos.
Semantic gateway	API que permite a agentes resolver términos, recuperar contexto, consultar entidades, explicar hechos y validar acciones.

SKOS es apropiado para glosarios, vocabularios, sinónimos y jerarquías terminológicas ligeras; OWL permite representar clases, propiedades, individuos y semántica formal; SHACL permite validar grafos mediante restricciones. No todos los términos deben convertirse en clases OWL: una parte importante será terminología SKOS y otra parte será modelo formal.

El producto no debería reemplazar los sistemas maestros. El grafo debe funcionar principalmente como:

Índice semántico de los sistemas de verdad.
Capa virtual sobre los datos existentes.
Repositorio materializado para entidades y hechos de alto valor.
Contrato de significado para aplicaciones y agentes.
2. Qué indica la investigación científica
2.1 Los LLM sirven para acelerar la construcción, no para ser la autoridad

LLMs4OL estudia tres tareas directamente relevantes: clasificación de términos, descubrimiento de taxonomías y extracción de relaciones no taxonómicas. Sus resultados muestran utilidad, pero también que los modelos base no son suficientemente fiables para construir ontologías complejas de forma autónoma; funcionan mejor como asistentes dentro de un proceso controlado. Trabajos posteriores como OLLM exploran la construcción end-to-end de la columna vertebral taxonómica, pero esta línea sigue siendo más apropiada para generar candidatos que para publicar modelos empresariales sin validación.

Por tanto, la regla de diseño debe ser:

El LLM propone; las fuentes, las reglas, los verificadores y los responsables humanos deciden.

2.2 No debes enviar todos los esquemas y toda la ontología en un único prompt

Un estudio experimental de schema matching encontró que tanto la falta de contexto como el exceso de contexto empeoran los resultados. EDC aborda el problema recuperando únicamente los elementos del esquema relevantes para cada fragmento de texto, y ReMatch aplica recuperación para reducir el espacio de posibles mappings.

La consecuencia arquitectónica es importante:

Clasificación jerárquica.
Recuperación top-k de conceptos candidatos.
Análisis por fuente, tabla, documento o data product.
Comparación únicamente contra módulos ontológicos relevantes.
Nunca cargar una ontología empresarial completa en el contexto del modelo.
2.3 Es mejor combinar extracción abierta y grounding contra esquemas conocidos

EDC propone una secuencia útil para el appliance: Extract → Define → Canonicalize. Primero extrae expresiones y relaciones, después define una estructura y finalmente canoniza los resultados contra un esquema. SPIRES demuestra otra ruta complementaria: dada una estructura definida por el usuario, el LLM puede devolver información que se ajuste a ella y vincular entidades a identificadores de ontologías existentes.

El appliance necesita ambos modos:

Modo discovery: cuando todavía no existe un modelo claro.
Modo alignment: cuando existen FIBO, FHIR, AIDM o una ontología interna y hay que alinear los datos locales.
2.4 El verificador no puede ser simplemente “otro prompt al mismo LLM”

FActScore propone dividir una salida en afirmaciones atómicas y comprobar cada una contra fuentes fiables. Chain-of-Verification genera preguntas independientes para verificar una respuesta. RARR busca evidencias y revisa el contenido no respaldado. SelfCheckGPT utiliza consistencia entre múltiples generaciones como señal de posible alucinación. Sin embargo, existen evidencias de que la autocorrección intrínseca puede fallar y de que los LLM utilizados como jueces presentan sesgos, por ejemplo, en función del orden de las opciones.

La conclusión para el producto es:

El LLM verifier no es un modelo. Es un sistema de pruebas que combina evidencia, validaciones deterministas, modelos independientes y revisión humana.

3. Arquitectura objetivo
 ┌─────────────────────────────────────────────────────────────┐
 │ FUENTES EMPRESARIALES                                      │
 │ DBs · Data lakes · APIs · SaaS · Eventos · PDFs · Wikis    │
 │ Catálogos · BI models · Data contracts · Lineage · Logs    │
 └─────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ 1. EVIDENCE & METADATA PLANE                               │
 │ Inventario · profiling · estadísticas · muestras · lineage │
 │ documentos · permisos · calidad · provenance               │
 └─────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ 2. AGENTIC DISCOVERY                                       │
 │ Domain classifier · terminology miner · schema matcher     │
 │ relation miner · constraint miner · entity resolver        │
 └─────────────────────────────┬───────────────────────────────┘
                               │ propuestas
                               ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ 3. ONTOLOGY FACTORY                                        │
 │ Core ontology + domain packs + company overlay             │
 │ mappings + shapes + competency questions                   │
 └─────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ 4. VERIFICATION FABRIC                                     │
 │ SHACL/OWL · SQL tests · evidence entailment · contradiction│
 │ independent LLM · graph tests · human stewardship          │
 └─────────────────────────────┬───────────────────────────────┘
                               │ aprobado
                               ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ 5. SEMANTIC RUNTIME                                        │
 │ Ontology registry · virtual KG · materialized KG           │
 │ entity index · provenance graph · versioning               │
 └─────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ 6. SEMANTIC GATEWAY                                        │
 │ Resolve · Query · Explain · Validate · Get Context          │
 │ APIs para agentes, copilots, workflows y aplicaciones      │
 └─────────────────────────────────────────────────────────────┘

Seguridad, gobierno, observabilidad, políticas, costes y routing de modelos atraviesan todas las capas. Dentro de Optiak, esta arquitectura puede reutilizar el gateway de modelos, el control de acceso, la observabilidad y el prompt journey ya planteados en el documento.

4. Las capas del modelo semántico

No crearía una gran ontología universal monolítica. Usaría un modelo modular de seis niveles.

Nivel 1: Core empresarial

Conceptos que aparecen en casi todas las organizaciones:

Persona, organización y rol.
Producto y servicio.
Cliente, proveedor y empleado.
Activo y recurso.
Contrato y acuerdo.
Cuenta.
Documento.
Localización.
Evento y proceso.
Medición y métrica.
Política, obligación y riesgo.
Sistema, dataset, aplicación, agente y modelo.

Un patrón especialmente útil es modelar los eventos como nodos de primera clase. Una transacción bancaria, un encuentro clínico o un vuelo tienen participantes, tiempo, lugar, estado y provenance; normalmente son demasiado ricos para representarlos como una simple arista.

Nivel 2: Packs horizontales

Módulos reutilizables entre industrias:

Identidad y organizaciones.
Legal y contratos.
Riesgo y compliance.
Finanzas y contabilidad.
Producto y cliente.
Recursos humanos.
Datos, IA y software.
Tiempo, localización y mediciones.
Nivel 3: Packs verticales

Modelos específicos de banca, salud, aerolíneas, seguros, telecomunicaciones, energía o industria.

Nivel 4: Overlay de la empresa

Términos y reglas locales:

“Cliente oro”.
“Cuenta operativa”.
“Vuelo protegido”.
“Paciente complejo”.
Acrónimos internos.
Jerarquías organizativas.
Clasificaciones y políticas propias.

La interfaz no debe obligar a la empresa a abandonar sus términos. Debe permitir que utilice su lenguaje y, por debajo, mantener mappings hacia estándares.

Nivel 5: Bindings físicos

Relaciones entre el modelo y los datos:

Concepto Customer
 ├── crm.customer.customer_id
 ├── core_banking.cif.client_number
 ├── support.contacts.account_holder
 └── api/customers/{id}
Nivel 6: Instancias, acciones y políticas
Instancias concretas y relaciones.
Acciones disponibles.
Precondiciones.
Permisos.
Efectos.
Compensaciones.
Políticas aplicables.

Esta última capa convierte una ontología descriptiva en una ontología operativa.

5. Stack de estándares recomendado

Usaría estándares abiertos como formato canónico, aunque el runtime pueda utilizar otros índices o bases de datos internamente.

Necesidad	Estándar recomendado
Representación base	RDF y JSON-LD
Clases y relaciones formales	OWL 2
Glosarios, sinónimos y traducciones	SKOS
Restricciones y validación	SHACL
Provenance	PROV-O
Catálogo de datasets y servicios	DCAT
Mappings relacional → grafo	R2RML
Lineage de pipelines y columnas	OpenLineage
Consulta experta	SPARQL
Consumo por aplicaciones	REST, GraphQL y JSON

OWL 2 proporciona semántica formal para clases, propiedades e individuos; SHACL valida la estructura de los grafos; PROV-O permite representar de dónde procede una afirmación; R2RML define mappings de bases relacionales a RDF; DCAT facilita representar datasets y servicios de datos.

OpenLineage puede incorporarse para representar jobs, runs, datasets y dependencias de columnas, lo que permitirá navegar desde un concepto de negocio hasta las tablas, transformaciones y dashboards que lo producen.

Decisión práctica importante

Mantendría:

RDF/OWL/SKOS como modelo canónico portable.
Un índice de búsqueda léxica y vectorial para discovery.
Un graph runtime optimizado para consultas operativas.
Mappings virtuales para no copiar todos los datos.

R2RML permite expresar mappings desde bases relacionales hacia RDF. Plataformas de virtualización demuestran que las consultas semánticas pueden traducirse a SQL y ejecutarse sobre el sistema original, sin duplicar necesariamente todos los datos.

6. Flujo completo: fuentes → terminología → ontología → autopoblado
Paso 1. Empezar por preguntas de negocio

Antes de escanear la empresa, el onboarding debe pedir entre cinco y veinte competency questions:

¿Qué clientes están relacionados con una empresa sancionada?
¿Qué pacientes recibieron un medicamento incompatible con una alergia?
¿Qué vuelos se verían afectados por dejar un avión fuera de servicio?
¿Qué contratos dependen de un proveedor concreto?
¿Qué agentes acceden a información clasificada como sensible?

Estas preguntas delimitan qué conceptos, fuentes y relaciones tienen valor. Evitan generar miles de nodos irrelevantes.

Paso 2. Inventario de fuentes

Los conectores se despliegan con permisos de solo lectura y recogen inicialmente:

Nombres y descripciones de sistemas.
Tablas, columnas, tipos y claves.
OpenAPI, JSON Schema, XML Schema.
Modelos BI y métricas.
Catálogos y glosarios.
Lineage.
Políticas y documentación.
Logs de consultas y joins frecuentes.
Propietarios, permisos y clasificaciones.

La inspección debe ser metadata-first. Las muestras de valores se habilitan únicamente bajo política explícita.

Paso 3. Profiling estructural

El profiler detecta:

Claves primarias y candidatas.
Claves foráneas declaradas y probables.
Unicidad y cardinalidades.
Distribuciones y valores dominantes.
Patrones de identificadores.
Unidades y códigos.
Fechas, periodos y granularidad temporal.
Posibles datos personales o sensibles.
Tablas de hechos, dimensiones y eventos.

La salida no es todavía una ontología. Es un perfil de evidencia.

Paso 4. Clasificación de dominios

No debe existir una única etiqueta para toda la empresa. La clasificación debe ser multi-label y producir probabilidades por:

Fuente.
Data product.
Esquema.
Tabla.
Documento.
Campo.
Proceso.

Un banco también tiene recursos humanos, legal, marketing y tecnología. Un hospital tiene facturación y supply chain. Una aerolínea tiene pasajeros, mantenimiento, carga, fidelización y finanzas.

El clasificador combina:

evidencia léxica
+ coincidencia con terminologías
+ patrones de códigos
+ topología del esquema
+ documentación
+ sistemas de origen
+ joins y lineage
+ clasificación LLM respaldada por evidencias

La salida podría ser:

payments_schema:
  banking.payments: 0.94
  banking.customer: 0.72
  risk.aml: 0.64
  generic.accounting: 0.31
Paso 5. Activación de domain packs

El sistema recupera únicamente los módulos relevantes. Un pack debe contener:

Ontología o modelo sectorial.
Terminología y sinónimos.
Mappings hacia otros estándares.
Restricciones SHACL.
Patrones de extracción.
Ejemplos aceptados.
Reglas de entity resolution.
Competency questions.
Tests.
Versiones y licencias.
Política de riesgo.
Responsables recomendados.
Paso 6. Extracción de terminología local

El terminology agent extrae:

Términos de tablas y columnas.
Definiciones en glosarios.
Acrónimos.
Sinónimos.
Variantes en distintos idiomas.
Términos con múltiples significados.
Términos de documentos y procesos.

Por ejemplo:

CIF
client
customer
party
account holder
titular
contratante
beneficial owner
UBO

El sistema no los fusiona automáticamente. Propone clusters contextuales y distingue:

Sinónimo exacto.
Correspondencia aproximada.
Concepto más amplio.
Concepto más específico.
Uso local.
Homónimo con otro significado.
Paso 7. Generación del modelo candidato

Se generan propuestas de:

Clases.
Propiedades.
Jerarquías.
Relaciones.
Cardinalidades.
Restricciones.
Definiciones.
Sinónimos.
Mappings a estándares.

El modelo puede trabajar en dos direcciones:

bottom-up:
datos y documentos → conceptos candidatos

top-down:
domain pack → búsqueda de realizaciones en los datos

La mejor arquitectura combina ambos caminos.

Paso 8. Descubrimiento de relaciones

Las relaciones se extraen de varias señales:

Evidencia	Ejemplo
Foreign key	account.customer_id → customer.id
Lineage	Un campo se deriva de otras dos columnas.
Joins frecuentes	Dos tablas se consultan habitualmente juntas.
Documentación	“El titular controla la cuenta”.
Eventos	Un cliente inicia una transferencia.
Estándar sectorial	FIBO define una relación financiera conocida.
LLM	Propone una relación a partir de nombres y contexto.

La jerarquía de confianza debe dar más peso a restricciones declaradas y documentos autorizados que a inferencias puramente lingüísticas.

Paso 9. Schema matching

Para cada campo se recuperan solamente los conceptos candidatos más relevantes. El matcher combina:

Coincidencia léxica.
Embeddings.
Descripciones.
Tipo de dato.
Valores y unidades.
Posición en el esquema.
Relaciones con otros campos.
Estándares del pack.
Ejemplos aceptados anteriormente.

La investigación recomienda este proceso de recuperación limitada, porque tanto muy poco como demasiado contexto pueden reducir la calidad del matching.

Paso 10. Entity resolution

El LLM no debe comparar todas las filas contra todas las filas. El proceso escalable sería:

Identificadores exactos y estándares.
Normalización determinista.
Blocking de candidatos.
Matching probabilístico.
Embeddings y reglas sectoriales.
LLM solamente para pares ambiguos.
Revisión humana para merges de alto impacto.

La investigación sobre entity resolution con LLM también identifica coste y escalabilidad como problemas centrales y propone priorizar las preguntas que más reducen la incertidumbre.

Paso 11. Autopoblado

Hay que separar dos cosas:

Autopoblado del modelo

Creación de conceptos, relaciones, mappings y restricciones.

Autopoblado del grafo

Creación de entidades y hechos concretos.

Recomiendo un enfoque virtual-first:

Las tablas permanecen en origen.
Se crean mappings semánticos.
Se materializan únicamente entidades críticas.
Los hechos extraídos de documentos sí se almacenan con su evidencia.
Los datos operativos calientes pueden materializarse para rendimiento.
Los demás se consultan virtualmente.

No todas las filas necesitan convertirse en nodos. Algunas columnas deben seguir siendo atributos o medidas.

Paso 12. Publicación y evolución

Los artefactos aprobados se publican como una versión:

Ontology version: 1.4.0
Domain packs:
  enterprise-core: 2.1
  banking-core: 3.4
  aml-kyc: 1.2
Company overlay: bank-x 1.4
Mappings: 482
Verified assertions: 12,540
Pending review: 87

Después, el sistema monitoriza:

Cambios de esquemas.
Nuevos términos.
Columnas eliminadas.
Mappings rotos.
Violaciones SHACL.
Cambios de distribución.
Nuevas versiones de estándares.
Disminución de cobertura.
Contradicciones nuevas.

Cada cambio crea una propuesta y un análisis de impacto, no una modificación silenciosa.

7. Domain packs: banca, salud y aerolíneas
Banca

FIBO es una ontología formal de conceptos financieros y sus relaciones. ISO 20022 proporciona un marco para procesos, elementos de datos y mensajes financieros estructurados. El pack bancario debería utilizar FIBO como modelo conceptual y los mensajes ISO 20022 como una fuente adicional de estructuras y términos operativos.

Conceptos iniciales:

Party
LegalEntity
Person
Customer
Account
FinancialInstrument
Payment
Transaction
Counterparty
BeneficialOwner
Mandate
Exposure
Risk
Sanction
Investigation

Primer subdominio recomendado: KYC/AML y customer-account-payment, porque obliga a resolver terminología, relaciones y entity resolution entre CRM, core bancario, pagos, compliance y documentos.

Salud

FHIR es un estándar de intercambio de información sanitaria basado en recursos. SNOMED CT es una terminología clínica lógica y multilingüe. LOINC proporciona identificadores para observaciones, mediciones y documentos sanitarios. No deben tratarse como equivalentes: FHIR aporta estructura de intercambio, mientras que SNOMED y LOINC aportan terminología y códigos.

Conceptos iniciales:

Patient
Practitioner
Encounter
Observation
Condition
Procedure
Medication
Allergy
Specimen
DiagnosticReport
CarePlan
Organization
Location

En este dominio se deben aplicar los umbrales más restrictivos: las inferencias clínicas no deben convertirse automáticamente en hechos asistenciales.

Aerolíneas

IATA AIDM proporciona vocabulario, definiciones y relaciones acordadas para el sector. ONE Record define un modelo común y APIs para compartir información de carga aérea, utilizando una estructura basada en JSON-LD.

Conceptos iniciales:

Flight
FlightLeg
Airport
Aircraft
TailNumber
Passenger
Booking
PNR
Ticket
Baggage
Crew
Rotation
MaintenanceEvent
Shipment
AirWaybill
ULD
Disruption

Un primer caso útil sería flight-aircraft-disruption, conectando planificación, operaciones, mantenimiento, pasajeros y compensaciones.

Gestión de licencias

El registry de packs debe incorporar licencias como metadatos ejecutables. Algunas terminologías permiten usos amplios con condiciones; otras dependen del país o del tipo de distribución. SNOMED CT, por ejemplo, tiene requisitos específicos de licenciamiento, mientras que LOINC permite uso comercial y no comercial bajo determinadas condiciones.

Un pack debería registrar:

license
territories
redistribution_allowed
derivative_rules
attribution
version
expiry
customer_entitlement
8. Arquitectura agéntica recomendada

No usaría un “swarm” libre de agentes. Usaría un workflow duradero y reproducible, con estados, contratos tipados y separación de responsabilidades.

Agente	Responsabilidad	Restricción principal
Source Scout	Inventariar sistemas y metadatos.	Solo lectura.
Profiler	Analizar estructura, claves, distribuciones y calidad.	No propone semántica por sí solo.
Domain Classifier	Asignar dominios y seleccionar packs.	Debe mostrar evidencias.
Terminology Miner	Extraer términos, sinónimos y definiciones.	No fusiona conceptos directamente.
Ontology Proposer	Proponer clases, jerarquías y relaciones.	Solo escribe en staging.
Schema Mapper	Vincular conceptos con campos y APIs.	Debe producir tests ejecutables.
Entity Resolver	Detectar entidades duplicadas o relacionadas.	LLM solo sobre pares ambiguos.
Constraint Miner	Proponer cardinalidades y reglas.	No convierte patrones estadísticos en reglas duras sin revisión.
Verifier	Validar propuestas y evidencias.	No puede aprobar su propia generación.
Steward Router	Asignar revisiones al experto adecuado.	Prioriza por impacto e incertidumbre.
Publisher	Publicar versiones aprobadas.	Único componente con escritura en producción.
Drift Monitor	Detectar cambios y mappings rotos.	Genera propuestas, no cambios directos.

Cada agente debe recibir y devolver objetos estructurados. Por ejemplo:

{
  "proposal_id": "map-01882",
  "proposal_type": "source_mapping",
  "concept": "enterprise:Customer",
  "source_asset": "core_banking.customer_master",
  "source_field": "cif_no",
  "mapping_type": "identifier",
  "evidence": [
    "schema-description",
    "data-profile",
    "business-glossary-entry"
  ],
  "generator": {
    "model": "generator-A",
    "prompt_version": "mapping-3.2"
  },
  "status": "pending_verification"
}
9. Diseño del LLM Verifier
9.1 El verifier debe validar objetos atómicos

Las unidades de validación deberían ser:

Una definición.
Un sinónimo.
Una relación.
Una relación taxonómica.
Un mapping.
Una restricción.
Un merge de entidades.
Un hecho del grafo.
Una acción o precondición.

Esto sigue el principio de FActScore: dividir una salida compleja en afirmaciones pequeñas que puedan comprobarse individualmente.

9.2 Pipeline de verificación
Gate 1: Validación sintáctica y de contrato
JSON válido.
Campos requeridos.
Tipos válidos.
Identificadores existentes.
Sin referencias rotas.
Evidencias accesibles.
Gate 2: Validación ontológica determinista
Dominio y rango.
Cardinalidades.
Ciclos en taxonomías que deban ser acíclicas.
Clases inconsistentes.
Tipos incompatibles.
Restricciones SHACL.
Reglas de naming y versionado.

SHACL está diseñado específicamente para validar grafos RDF contra shapes y restricciones.

Gate 3: Validación contra la fuente

Para cada propuesta se recupera evidencia original:

Fila o conjunto de filas.
Definición de columna.
Fragmento de documento.
Resultado de una query.
Constraint de base de datos.
Entrada del glosario.
Concepto del estándar.
Evento de lineage.

El verifier clasifica:

ENTAILED       La evidencia respalda la propuesta.
CONTRADICTED   La evidencia la contradice.
INSUFFICIENT   No existe evidencia suficiente.
AMBIGUOUS      Existen interpretaciones alternativas.

No debe poder responder “ENTAILED” sin devolver referencias concretas a las evidencias utilizadas.

Gate 4: Preguntas de verificación independientes

Inspirado en Chain-of-Verification:

Se genera la propuesta.
Otro proceso genera preguntas para intentar refutarla.
Las preguntas se responden sin mostrar al verificador la conclusión original.
Se comparan los resultados.
Se revisa o rechaza la propuesta.

Ejemplo para cif_no → Customer.identifier:

¿El campo es único por cliente?
¿Puede cambiar a lo largo del tiempo?
¿Identifica una persona, una relación contractual o un expediente?
¿Aparece en varias tablas con significados distintos?
¿La documentación lo denomina customer identifier?
¿Existen valores compartidos por varias entidades?
Gate 5: Consistencia entre modelos y ejecuciones

SelfCheckGPT sugiere que la divergencia entre múltiples generaciones puede servir como señal de posible alucinación. En el appliance, esta señal se utilizaría como indicador de incertidumbre, nunca como prueba de verdad.

Para cambios importantes:

Generador y verificador de familias distintas.
Varias formulaciones del prompt.
Orden de candidatos intercambiado.
Repetición de la evaluación.
Comprobación de consistencia.

El intercambio del orden es importante porque los LLM jueces pueden mostrar sesgo posicional.

Gate 6: Tests sobre los datos

Para un mapping:

Cobertura.
Porcentaje de nulos.
Unicidad.
Integridad referencial.
Distribución.
Cardinalidad.
Compatibilidad de unidades.
Estabilidad temporal.
Contraejemplos.

Para una relación:

Número de sujetos y objetos.
Casos uno-a-uno, uno-a-varios o varios-a-varios.
Excepciones.
Cambios históricos.
Relaciones conflictivas.
Gate 7: Consistencia global del grafo

Una propuesta local puede ser plausible y, aun así, romper el modelo global. Se comprueba:

Contradicción con otras relaciones.
Duplicación de conceptos.
Clases imposibles.
Mappings incompatibles.
Identidades conflictivas.
Cambios en competency questions.
Impacto en agentes, queries y dashboards.
Gate 8: Adjudicación y revisión humana

Estados finales:

AUTO_APPROVED
HUMAN_REVIEW
REJECTED
QUARANTINED
ABSTAINED

ABSTAINED debe ser una salida normal. Obligar al modelo a tomar una decisión en todos los casos incrementaría errores.

9.3 La confianza debe ser un vector, no un número mágico

No aceptaría que el LLM diga “confianza 0,93” y convertiría eso en verdad. Guardaría componentes separados:

evidence_strength
source_authority
schema_consistency
graph_consistency
data_test_score
independent_model_agreement
counterexample_rate
coverage
recency
business_impact

Después se calibran umbrales con un conjunto de validación etiquetado por expertos.

9.4 Política por tipo de cambio
Propuesta	Automatización recomendada
Nuevo alias o traducción	Puede autoaprobarse con evidencia fuerte.
Mapping de columna	Autoaprobable si supera tests y es de bajo riesgo.
Nueva clase	Revisión de steward.
Nueva relación empresarial	Revisión de steward o experto de dominio.
Cambio de jerarquía	Revisión obligatoria e impacto.
Merge de entidades	Revisión según riesgo e impacto.
Eliminación o deprecación	Revisión obligatoria.
Inferencia clínica o regulatoria	Nunca publicar solo por consenso de LLM.
Acción con efectos en sistemas	Revisión, autorización y políticas adicionales.
10. Ejemplo concreto: onboarding de un banco
Fuentes conectadas
CRM
Core banking
Payments
AML cases
Customer documents
Contracts
Sanctions provider
Enterprise glossary
BI semantic model
Discovery inicial

El sistema detecta:

cif_no
client_id
party_key
account_holder_id
debtor
creditor
ubo
legal_entity_id
beneficiary
counterparty
Domain classification

Activa:

enterprise-core
banking-core
payments
kyc-aml
legal-entity
risk-compliance
Propuestas
cif_no → Party.identifier
client_id → Customer.identifier
ubo → BeneficialOwner
debtor → PaymentOriginator
creditor → PaymentBeneficiary
account_holder_id → AccountHolder
Relaciones propuestas
Customer --holdsRole--> AccountHolder
AccountHolder --controls--> Account
Payment --debitedFrom--> Account
Payment --creditedTo--> Account
Person --beneficialOwnerOf--> LegalEntity
LegalEntity --subjectTo--> Sanction
AMLCase --investigates--> Party
Verificación

Para ubo → BeneficialOwner:

Se recupera la descripción del campo.
Se inspeccionan documentos KYC.
Se comprueba el pack FIBO.
Se analizan valores y cardinalidades.
El verificador busca contraejemplos.
Un experto de compliance aprueba la relación.
Se publica con provenance.
Resultado para los agentes

Un agente puede recibir una pregunta como:

“Identifica cuentas relacionadas con personas que controlan una entidad sancionada y explica la cadena de relación.”

La ejecución semántica sería:

intención
→ Party / BeneficialOwner / LegalEntity / Sanction / Account
→ mappings físicos
→ queries en CRM, KYC, core y sanctions
→ entity resolution
→ recorrido del grafo
→ verificación del resultado
→ respuesta con evidencias

El agente no necesita conocer los nombres de tablas ni las diferencias entre cif_no, party_key y client_id.

11. Cómo se integraría con Optiak

Añadiría cinco módulos al control plane de Optiak.

11.1 Semantic Discovery

Conectores, profiling, clasificación de dominios y extracción de terminología.

11.2 Ontology Registry

Versiones de:

Core ontology.
Domain packs.
Company overlay.
Mappings.
Shapes.
Reglas.
Acciones.
Políticas.
11.3 Semantic Memory

La memoria de los agentes no guarda únicamente texto. Guarda referencias estables:

ontology_version
entity_ids
concept_ids
source_evidence
valid_time
permissions

Esto evita que distintos agentes creen interpretaciones incompatibles del mismo concepto.

11.4 Verification Fabric

Optiak puede utilizar su routing de modelos para separar:

Modelo generador.
Modelo verificador.
Modelo de adjudicación.
Modelos locales para datos sensibles.
Validadores deterministas.
11.5 Semantic Observability

En el dashboard incorporaría:

Cobertura de fuentes.
Cobertura ontológica.
Conceptos sin owner.
Mappings aprobados y pendientes.
Violaciones SHACL.
Entidades ambiguas.
Disagreement entre verificadores.
Drift.
Coste de discovery.
Tiempo de revisión.
Porcentaje de respuestas de agentes con provenance.

En el prompt journey mostraría:

pregunta
→ conceptos detectados
→ subgrafo recuperado
→ fuentes consultadas
→ mappings utilizados
→ queries ejecutadas
→ afirmaciones producidas
→ verificaciones
→ respuesta final
12. Despliegue como appliance empresarial

La arquitectura de despliegue más adecuada es separar un data plane local y un control plane opcional del proveedor.

Data plane local

Dentro del VPC, datacenter o entorno aislado del cliente:

Conectores.
Metadata store.
Evidence store.
Graph runtime.
Vector y lexical index.
Workflow engine.
Model adapters.
Verifier.
Policy enforcement.
Steward console.
Audit log.
Control plane opcional

Puede gestionar, sin recibir datos empresariales:

Actualizaciones firmadas.
Domain packs.
Licencias.
Compatibilidad.
Telemetría técnica agregada.
Nuevos tests.
Benchmarks.
Vulnerabilidades y dependencias.
Controles esenciales
Credenciales de solo lectura por defecto.
Egress deshabilitado o allowlisted.
Modelos locales para datos sensibles.
Redacción y tokenización.
Separación entre staging y producción.
Cifrado por tenant.
OIDC/SAML.
RBAC y ABAC.
Auditoría inmutable.
Firma de domain packs.
Registro de modelo, prompt, versión y evidencia.
Reproducción completa de cada decisión.

El NIST AI RMF y su perfil para IA generativa recomiendan gestionar los riesgos según el contexto, la tolerancia al riesgo y el ciclo de vida, e incorporar testing, evaluación, verificación y validación. Ese enfoque encaja con los risk tiers del verifier.

13. Posicionamiento respecto al mercado

La categoría ya está validada, aunque los productos existentes se concentran en partes distintas del problema.

Plataforma	Énfasis público
Palantir Foundry Ontology	Objetos, propiedades, links, acciones y funciones vinculados a datos operativos.
Stardog	Knowledge graphs, mappings y virtualización de fuentes mediante consultas semánticas.
DataHub	Glosario empresarial y asociación de términos con activos de datos.
Microsoft Fabric IQ Ontology	Vocabulario y capa semántica sobre fuentes de OneLake; actualmente documentada como preview.

Mi inferencia, limitada a la documentación pública revisada, es que el espacio diferenciador para Optiak sería la combinación de:

Instalación en cualquier entorno.
Independencia de cloud, modelo y graph database.
Discovery multi-source automático.
Packs sectoriales componibles.
Ontología corporativa local.
Verificador basado en evidencia.
Integración nativa con agentes.
Trazabilidad semántica de cada respuesta y acción.
Aprendizaje entre instalaciones sin compartir datos empresariales.

El moat no sería el graph database. Serían:

La biblioteca de domain packs.
Los mappings aceptados.
Los conjuntos de evaluación.
Los casos negativos y contraejemplos.
El sistema de verificación.
La experiencia de revisión por stewards.
Los conectores.
El historial de evolución y drift.
14. MVP recomendado

No intentaría empezar con “toda la empresa” ni con “toda la banca”. El primer producto debe resolver un subdominio con relaciones claras y valor medible.

Primer design partner recomendado

KYC/AML bancario: Party–Legal Entity–Account–Payment.

Razones:

Existen FIBO e ISO 20022.
Hay terminología inconsistente entre muchas fuentes.
Entity resolution es un problema real.
La provenance es esencial.
El valor de una vista semántica unificada es fácil de demostrar.
Puede ejecutarse inicialmente en modo read-only.
Alcance del piloto
3–5 fuentes estructuradas
1 repositorio documental
30–50 conceptos
15–25 relaciones
100–200 mappings
5 competency questions
1 domain pack
1 company overlay
2 modelos distintos
SHACL + SQL tests + evidence verifier
Fases indicativas
Fase 0 — Definición, 2 semanas
Competency questions.
Selección de fuentes.
Conceptos iniciales.
Política de riesgo.
Dataset de evaluación.
Fase 1 — Discovery, 4 semanas
Conectores.
Metadata inventory.
Profiling.
Domain classifier.
Terminology miner.
Fase 2 — Ontología y mappings, 4 semanas
Core.
FIBO subset.
Company overlay.
Schema matcher.
Relation discovery.
Entity resolution inicial.
Fase 3 — Verifier y gateway, 4 semanas
SHACL.
Evidence verifier.
Review UI.
Virtual graph.
Semantic API.
Agent integration.

Un piloto completo razonable sería de aproximadamente doce a catorce semanas, dependiendo del acceso a fuentes y expertos.

Targets del piloto

Los siguientes serían objetivos de producto, no garantías de la literatura:

100 % de propuestas con provenance.
Más de 95 % de precisión en mappings autoaprobados.
Más de 80 % de aceptación de propuestas de alta confianza.
Cero cambios de alto riesgo sin aprobación humana.
Resolución correcta de al menos cuatro de cinco competency questions.
Reducción clara del tiempo necesario para incorporar una nueva fuente.
Reproducción completa de cada respuesta del agente.
15. Riesgos y anti-patrones
Riesgo	Mitigación
Una ontología gigante e inmanejable	Core pequeño, packs y overlays modulares.
El LLM alucina relaciones	Staging, evidence graph, verifier y revisión.
Todo se convierte en un nodo	Virtual-first y criterios de materialización.
Fusiones erróneas de entidades	Blocking, matching probabilístico, LLM solo en ambigüedad y revisión por riesgo.
Uso incorrecto de sameAs	Utilizar mappings exactos, cercanos, amplios o estrechos; identidad fuerte solo cuando esté demostrada.
Prompts con esquemas enormes	Schema retrieval y procesamiento jerárquico.
Confianza opaca del modelo	Vector de evidencias y calibración.
Cambios silenciosos en estándares	Version pinning, migrations e impact analysis.
Problemas de licencias	License registry por domain pack.
El grafo se convierte en otro silo	APIs abiertas, RDF canónico y mappings exportables.
Agentes modifican directamente producción	Separación estricta entre proposer, verifier y publisher.
No hay propietario semántico	Owner y steward obligatorios para conceptos críticos.
16. Papers que deberían guiar el prototipo
LLMs4OL: descompone ontology learning en term typing, taxonomy discovery y extracción de relaciones; útil para diseñar los agentes especializados.
End-to-End Ontology Learning with Large Language Models: explora la generación de una columna vertebral taxonómica completa y métricas estructurales y semánticas.
Extract, Define, Canonicalize: muy relevante para discovery abierto, creación de esquema y posterior canonicalización, además de recuperación de elementos de esquemas grandes.
SPIRES / OntoGPT: demuestra extracción conforme a un esquema y grounding contra identificadores ontológicos existentes.
Schema Matching with Large Language Models y ReMatch: muestran la importancia de controlar el contexto y aplicar recuperación antes de preguntar al LLM.
FActScore: fundamento para transformar propuestas complejas en afirmaciones verificables y medir soporte por afirmación.
Chain-of-Verification y RARR: patrones para generar preguntas independientes, buscar atribución y corregir contenido no respaldado.
SelfCheckGPT: útil como señal secundaria de inconsistencia entre generaciones.
Large Language Models Cannot Self-Correct Reasoning Yet y los estudios de sesgo en LLM-as-a-Judge: justifican que el verifier incorpore fuentes externas, tests deterministas, inversión de orden y revisión humana.

Arquitectura modular: core empresarial + domain packs + overlay local + mappings.
Virtual-first y estándares abiertos: RDF/OWL/SKOS/SHACL/PROV-O como representación portable, sin obligar a copiar todos los datos.
LLM como proposer, nunca como autoridad: todas las propuestas pasan por evidencia, validadores, modelos independientes y aprobación basada en riesgo.