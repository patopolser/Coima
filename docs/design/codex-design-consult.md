**Recomiendo Nácar:** fondo celeste muy claro, datos sobre blanco y vidrio concentrado en navegación y controles. La mejora principal debe ser jerarquizar la información: resumen primero, evidencia después, metodología a pedido.

Revisé el código solicitado sin modificar archivos. El diagnóstico es estático; los contrastes están calculados, pero no hice una validación visual en navegador.

Los ocho problemas más graves son:

1. **El texto secundario desaparece demasiado.** `--text-muted: #4A5170` alcanza apenas **2,25:1 a 2,57:1** sobre los tres fondos actuales. Se usa en encabezados, ayudas y etiquetas necesarias para interpretar datos. [index.css:24](/X:/Code/Coima-Public/frontend/src/index.css:24).

2. **La jerarquía depende de achicar texto.** Encabezados de tablas, etiquetas KPI y pills usan 11 px, mayúsculas y espaciado extra. Las sinergias bajan a 10 px. Eso aumenta el esfuerzo de lectura. [index.css:206](/X:/Code/Coima-Public/frontend/src/index.css:206), [index.css:218](/X:/Code/Coima-Public/frontend/src/index.css:218), [EvidenceBreakdown.jsx:52](/X:/Code/Coima-Public/frontend/src/components/EvidenceBreakdown.jsx:52).

3. **Tres advertencias legales compiten con el contenido.** Banner global, nota bajo el título y párrafo al pie repiten la misma idea. La nota además combina cursiva, 12 px y bajo contraste. [App.jsx:45](/X:/Code/Coima-Public/frontend/src/App.jsx:45), [LegalNote.jsx:10](/X:/Code/Coima-Public/frontend/src/components/LegalNote.jsx:10), [es.json:7](/X:/Code/Coima-Public/frontend/src/i18n/locales/es.json:7).

4. **CompanyDetail muestra todo junto.** Todas las banderas, todo el desglose y hasta 50 filas por detector aparecen desplegados. El usuario debe encontrar la síntesis dentro del detalle. [CompanyDetail.jsx:61](/X:/Code/Coima-Public/frontend/src/pages/CompanyDetail.jsx:61), [CompanyDetail.jsx:73](/X:/Code/Coima-Public/frontend/src/pages/CompanyDetail.jsx:73), [CompanyDetail.jsx:98](/X:/Code/Coima-Public/frontend/src/pages/CompanyDetail.jsx:98).

5. **La fórmula tiene demasiado protagonismo.** Sinergias, peso, intensidad, contribución y centralidad aparecen antes de que el usuario elija profundizar. Incluso se dedica espacio a explicar que no hubo sinergias. [EvidenceBreakdown.jsx:31](/X:/Code/Coima-Public/frontend/src/components/EvidenceBreakdown.jsx:31), [EvidenceBreakdown.jsx:68](/X:/Code/Coima-Public/frontend/src/components/EvidenceBreakdown.jsx:68), [EvidenceBreakdown.jsx:101](/X:/Code/Coima-Public/frontend/src/components/EvidenceBreakdown.jsx:101).

6. **Dashboard mezcla análisis y operación.** Fechas para ejecutar detecciones y “Forzar Re-ejecución” dominan la cabecera. Luego cada detector repite “hallazgos” y “peso” con igual tratamiento. Es difícil identificar por dónde empezar. [Dashboard.jsx:66](/X:/Code/Coima-Public/frontend/src/pages/Dashboard.jsx:66), [Dashboard.jsx:129](/X:/Code/Coima-Public/frontend/src/pages/Dashboard.jsx:129).

7. **La codificación visual exige interpretación y puede inducir conclusiones incorrectas.** El riesgo muestra número y color sin nivel escrito; “Confianza” también usa colores de riesgo. “Registro Limpio” sugiere una certeza que los datos no sostienen. [ui/index.jsx:78](/X:/Code/Coima-Public/frontend/src/components/ui/index.jsx:78), [ui/index.jsx:135](/X:/Code/Coima-Public/frontend/src/components/ui/index.jsx:135), [es.json:100](/X:/Code/Coima-Public/frontend/src/i18n/locales/es.json:100).

8. **Settings funciona como un formulario técnico completamente expandido.** Descripciones, valores predeterminados y claves internas de parámetros están siempre visibles. Al desactivar un detector, toda su tarjeta baja a `opacity: 0.55`, incluida la explicación. [Settings.jsx:23](/X:/Code/Coima-Public/frontend/src/pages/Settings.jsx:23), [Settings.jsx:52](/X:/Code/Coima-Public/frontend/src/pages/Settings.jsx:52), [Settings.jsx:130](/X:/Code/Coima-Public/frontend/src/pages/Settings.jsx:130).

Las tres direcciones siguientes cambian composición, densidad y carácter, además del color. Todas son exclusivamente claras, con `color-scheme: light`.

| Rol | Nácar | Folio | Prisma |
|---|---|---|---|
| Fondo | `#F1F7FC` | `#F8F7F2` | `#EAF4FA` |
| Superficie vidrio, hex con alfa | `#FFFFFFDB` | `#FFFFFFF0` | `#FFFFFFE6` |
| Superficie de datos | `#FFFFFF` | `#FFFFFF` | `#FFFFFF` |
| Texto 1, principal | `#14283D` | `#202C33` | `#102D3D` |
| Texto 2, secundario | `#354C63` | `#43515B` | `#355363` |
| Texto 3, metadatos | `#536479` | `#606B72` | `#516877` |
| Acento interactivo | `#176A96` | `#246C8B` | `#075F87` |
| Celeste decorativo | `#DCEFFA` | `#E5F0F5` | `#CFEAF7` |
| Oro decorativo | `#A17B32` | `#92702E` | `#9A752F` |

Los tres niveles de texto superan **5:1** sobre su fondo y sobre blanco. El oro queda reservado a ornamentación, sin texto informativo.

**La escala de riesgo sería idéntica en las tres direcciones.** Estos pares forman parte de las tres paletas:

| Nivel | Texto e icono | Fondo opaco del badge | Contraste calculado |
|---|---|---|---|
| Bajo | `#166534` | `#F0FDF4` | **6,81:1** |
| Medio | `#854D0E` | `#FFFBEB` | **6,61:1** |
| Alto | `#B91C1C` | `#FEF2F2` | **5,91:1** |
| Crítico | `#881337` | `#FFF1F2` | **8,71:1** |

Verifiqué los pares con luminancia relativa sRGB: todos superan el mínimo AA de **4,5:1 para texto normal**. La verificación corresponde a esos fondos opacos, sin transparencia ni opacidad aplicada al contenedor. [Criterio de contraste de W3C](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).

Siempre mostrar nivel escrito y puntaje. Mantener los cortes actuales: bajo `<40`, medio `40–59`, alto `60–79`, crítico `≥80`. El verde significa riesgo calculado bajo, nunca “empresa validada”. El ámbar aparece exclusivamente dentro de componentes de estado; el oro, en el motivo de marca.

**Nácar.** Una herramienta serena y precisa: composición abierta, pocas superficies grandes, bordes redondeados de 16 px y separación generosa entre bloques. El celeste construye ambiente; el blanco sostiene la lectura. Es la opción más equilibrada para investigar durante horas.

- **Tipografía:** [Inter](https://fonts.google.com/specimen/Inter), pesos 400, 500 y 600. Cuerpo 16/24 px, tablas 14/20 px, metadatos 13/18 px; cifras tabulares.
- **Doce estrellas:** corona SVG alrededor de la inicial del logo. El loader reutiliza esa corona con rotación de `1800ms linear`; fondos vacíos pueden llevarla al 3 % de opacidad, fuera del área de datos.
- **Vidrio:** `blur(16px) saturate(115%)`; borde `1px solid #FFFFFFCC`; sombra `0 8px 24px #183B5610`; brillo interior `inset 0 1px 0 #FFFFFF`. En hover, un reflejo de borde cambia de opacidad durante 140 ms.
- **CompanyDetail:** cabecera con nombre, CUIT y badge “Riesgo alto · 72/100”, como ejemplo de formato. Debajo, tres señales principales ordenadas por contribución. Pestañas “Hallazgos”, “Red” y “Cómo se calcula”; tablas cerradas por detector, con cinco filas al expandir y acceso al total.
- **Dashboard:** cuatro métricas en una sola banda; lista de detectores con nombre y cantidad. “Actualizar análisis” abre los controles de ejecución. El peso pasa a metodología.

**Folio.** Un expediente editorial contemporáneo: fondo blanco cálido, títulos con personalidad y lectura vertical. Predominan filas, divisores y márgenes; hay pocas tarjetas. Favorece trazabilidad, comparación y lectura de evidencia.

- **Tipografía:** [Source Sans 3](https://fonts.google.com/specimen/Source+Sans+3) para interfaz y datos; [Source Serif 4](https://fonts.google.com/specimen/Source+Serif+4) solamente para títulos de página. Cuerpo 16/24 px, tablas 15/22 px.
- **Doce estrellas:** sello pequeño, de trazo fino, junto a Coima. Loader estático con pulso conjunto de opacidad `1600ms cubic-bezier(.4,0,.6,1)`. Sin patrones detrás del expediente.
- **Vidrio:** `blur(8px) saturate(105%)`; borde `1px solid #D9E3E8`; sombra `0 3px 12px #24343D0D`; brillo `inset 0 1px 0 #FFFFFF`. Radio 8 px. Translucidez concentrada en cabecera y filtros.
- **CompanyDetail:** resumen compacto seguido de índice de detectores con conteos. Cada detector abre su evidencia en el mismo flujo. Fórmula y métricas de red quedan en “Metodología”; desaparece la fila duplicada de banderas.
- **Dashboard:** resumen numérico en línea y tabla “Detector / Hallazgos”. Una única cabecera reemplaza los rótulos repetidos en cada tarjeta. Fecha de análisis junto al título; operación dentro de un menú de acciones.

**Prisma.** Una estación de investigación con paneles: navegación compacta, lista principal y detalle lateral. El vidrio tiene más presencia, especialmente en herramientas y selección. La distinción está en poder explorar sin perder el contexto de la lista.

- **Tipografía:** [Manrope](https://fonts.google.com/specimen/Manrope) para títulos y navegación; Inter para datos. Cuerpo 15/23 px, tablas 14/20 px, títulos 28/34 px.
- **Doce estrellas:** constelación circular en el logo y loader de `2000ms linear`. Un único motivo grande al 2 % puede aparecer en un estado vacío. Nunca como nodos del grafo ni indicadores de riesgo.
- **Vidrio:** `blur(20px) saturate(125%)`; borde `1px solid #FFFFFFCC`; sombra `0 12px 32px #123C5714`; brillo `inset 0 1px 0 #FFFFFF`. Radio 20 px. Reflejo lateral de 220 ms al abrir un panel, animando transform y opacidad.
- **CompanyDetail:** lista de señales a la izquierda; seleccionar una muestra procesos y evidencia a la derecha. Puntaje fijo arriba; cálculo en panel desplegable. En móvil, lista y detalle se convierten en vistas consecutivas.
- **Dashboard:** tres métricas principales y una lista de detectores con barras neutrales de cantidad. “Cobertura” despliega proveedores, unidades y procesos. No sumar conteos de distintos detectores como si fueran procesos únicos.

El movimiento también distingue las direcciones:

| Interacción | Nácar | Folio | Prisma |
|---|---|---|---|
| Entrada de página | 220 ms, subir 6 px | 160 ms, opacidad | 260 ms, subir 8 px |
| Entrada de lista | 160 ms; escalón 20 ms, máximo 100 ms | 120 ms, bloque completo | 180 ms; escalón 24 ms, máximo 120 ms |
| Modal, abrir/cerrar | 200/140 ms; escala `.985 → 1` | 160/120 ms; opacidad | 240/160 ms; escala `.98 → 1` |
| Hover y brillo | 140 ms | 100 ms | 160 ms |
| Actualización numérica | fundido 160 ms | fundido 120 ms | fundido 180 ms |
| Curva de entrada | `cubic-bezier(.2,.8,.2,1)` | `cubic-bezier(.2,0,0,1)` | `cubic-bezier(.16,1,.3,1)` |
| Curva de salida | `cubic-bezier(.4,0,1,1)` | `cubic-bezier(.4,0,1,1)` | `cubic-bezier(.4,0,1,1)` |
| Hover y números | `cubic-bezier(.2,0,.2,1)` | `cubic-bezier(.2,0,.2,1)` | `cubic-bezier(.2,0,.2,1)` |

Los números muestran siempre valores reales: transición entre valor anterior y nuevo, sin contar desde cero ni atravesar niveles de riesgo ficticios. Con `prefers-reduced-motion`, duración cero, sin desplazamientos, reflejos ni loaders animados; permanece “Cargando”.

Para reducir texto en todo el producto, aplicaría estas reglas:

- **Tres niveles:** resumen visible, evidencia al abrir, metodología a pedido. Ningún dato desaparece.
- **Una etiqueta por conjunto:** “Hallazgos” en el encabezado de columna; las filas muestran cantidades.
- **Lenguaje consistente:** “Señales” para patrones detectados, “Hallazgos” para registros concretos, “Detectores” en configuración. Reemplazar “Registro Limpio” por “Sin señales detectadas en los datos analizados”.
- **Confianza explícita:** mostrar “3 detectores con señales”, con color neutral. Evitar que parezca una probabilidad de culpabilidad.
- **Tooltips para definiciones breves**, disponibles por teclado y toque. Las limitaciones esenciales quedan visibles junto al puntaje.
- **Settings por demanda:** fila con detector, estado y peso; “Configurar” despliega descripción, umbrales y valores predeterminados. Etiquetas traducidas en lugar de claves internas.
- **Preservar precisión:** CUIT, proceso, moneda, monto exacto y fecha accesibles en la evidencia. Abreviar montos solamente en resúmenes.
- **i18n desde el inicio:** frases completas, pluralización y formatos locales; evitar concatenaciones y anchos calculados para un único idioma.

Con el modal de términos, reorganizaría las capas legales así:

| Capa actual | Decisión |
|---|---|
| `DisclaimerBanner` | Reemplazar por el acceso bloqueante versionado. |
| `LegalNote` | Convertir en una frase junto al puntaje: “Indicador automático. Requiere verificación humana.” Enlace a alcance y metodología. |
| `LegalFooter` | Reemplazar el párrafo por “Términos y alcance · Solicitar rectificación”. |

**El modal** debe tener título “Antes de usar Coima”, resumen breve y texto completo accesible dentro del diálogo. Conservar los cinco temas de [DISCLAIMER.md:15](/X:/Code/Coima-Public/DISCLAIMER.md:15): naturaleza de los indicadores, calidad de datos, datos personales, garantías y rectificación.

Acciones: “Aceptar y entrar” y “No acepto”. Sin aceptación, queda una pantalla pública de acceso; no se montan las páginas de investigación. Escape o clic exterior nunca habilitan el producto. Mantener selector ES/EN, navegación por teclado, foco contenido y lectura cómoda del documento.

Guardar, por ejemplo, `coima.termsAcceptance = { version, acceptedAt }`. Una versión distinta exige nueva aceptación. El antiguo `coima.disclaimerDismissed` no cuenta como aceptación. Manejar errores de lectura y escritura de localStorage; si falla la persistencia, informar que se volverá a pedir al recargar. Ese registro es local al navegador.

**La 404** necesita una ruta `*`, hoy ausente en [App.jsx:47](/X:/Code/Coima-Public/frontend/src/App.jsx:47). Composición: luna creciente pequeña, doce estrellas discretas, “No encontramos esta página”, “Ir al panel” y “Buscar proveedor”. La luna aparece únicamente acá. Una empresa inexistente y un error de conexión necesitan estados propios.

Para el helper de animaciones, **recomiendo CSS + hooks propios**, con Web Animations API nativa solamente para reordenamientos que lo necesiten.

| Alternativa | Bundle | Evaluación |
|---|---|---|
| CSS + hooks | 0 kB de dependencias nuevas; código propio a medir | Alcanza para estas transiciones acotadas. |
| Motion | `motion`: aproximadamente 34 kB; `LazyMotion` y `m`: menos de 4,6 kB iniciales, más funciones cargadas | Conviene si aparecen gestos, drag o transiciones complejas de layout. |

Motion documenta módulos adicionales de aproximadamente 15 kB para `domAnimation` y 25 kB para `domMax`; los 4,6 kB no representan el costo total. Son cifras orientativas de su documentación, no mediciones del bundle de Coima. [Tamaño de Motion](https://motion.dev/docs/react-reduce-bundle-size). Es compatible con React 18.2, la versión declarada por el proyecto. [Compatibilidad](https://motion.dev/docs/react-installation).

La arquitectura propuesta, cuyos nombres serían internos nuevos:

- `motion.css`: duraciones, curvas y clases para entrada, salida, hover, brillo y loaders. Eliminar `transition: all`.
- `useReducedMotion`: suscripción compartida a `matchMedia`, incluyendo cambios durante la sesión.
- `usePresence`: mantener modales y paneles montados hasta completar la salida; finalización inmediata cuando se reduce movimiento.
- `PageTransition`: animar el contenedor de contenido al navegar, sin remontar proveedores globales ni perder estado innecesariamente.
- `AnimatedList`: claves estables, entrada limitada a elementos nuevos y visibles. Para reordenar, medir antes/después y animar con `Element.animate()`.
- `AnimatedValue`: fundido entre valores reales, ancho estable y anuncio accesible únicamente del valor final.

En React 18, efectos idempotentes y limpieza de listeners, timers y animaciones. Todo movimiento pasa por esta política común; foco, escritura y respuesta a controles permanecen inmediatos.

Los riesgos principales del rework son concretos:

- **Vidrio sobre tablas largas.** Muchos `backdrop-filter` implican superficies costosas durante el scroll. Usar tablas y filas opacas; reservar blur para navegación y un panel activo. Animar transform y opacidad, manteniendo blur y sombras grandes estáticos. [Guía de rendimiento](https://web.dev/articles/animations-guide).
- **Vidrio sobre Cytoscape.** Ya existen badges con blur y un panel translúcido encima del canvas en [GraphExplorer.jsx:612](/X:/Code/Coima-Public/frontend/src/pages/GraphExplorer.jsx:612). Llevar la leyenda afuera del canvas y dar fondo opaco al detalle. El paneo y zoom cambian continuamente lo que queda detrás del filtro.
- **Migración incompleta del grafo.** Sus etiquetas, selección y fondos contienen colores oscuros hardcodeados en [GraphExplorer.jsx:113](/X:/Code/Coima-Public/frontend/src/pages/GraphExplorer.jsx:113). Cambiar tokens CSS no alcanza. Además, reemplazar la estrella usada para funcionarios por otra forma para separar datos y motivo de marca.
- **Contraste variable.** El vidrio depende del contenido subyacente. Las verificaciones de la paleta no certifican cualquier composición translúcida. Mantener una capa opaca bajo datos y badges, y fallback blanco cuando no haya soporte para filtros.
- **Accesibilidad.** Controles con nombre accesible, foco visible, objetivos táctiles amplios y enlaces reales en tarjetas navegables. Color acompañado de texto; nada esencial disponible sólo por hover. Verificar zoom, teclado y movimiento reducido.
- **Densidad desplazada.** Colapsar contenido puede esconder evidencia importante. Cada sección cerrada debe conservar nombre, cantidad y una síntesis; la expansión debe ser directa y predecible.