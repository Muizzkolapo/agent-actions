from agent_actions.vendors.ollama_vendor import OllamaHandler

agent_cfg = {
    "model_vendor": "ollama",
    "model_name": "llama3",
    "json_mode": False
}

prompt_config = """
does the article below contain any information needed for this sylabys 
Topic 1: Developing dbt models
● Identifying and verifying any raw object
dependencies
● Understanding core dbt materializations
● Conceptualizing modularity and how to incorporate
DRY principles
● Converting business logic into performant SQL
queries
● Using commands such as run, test, docs and seed
● Creating a logical flow of models and building clean
DAGs
● Defining configurations in dbt_project.yml
● Configuring sources in dbt
● Using dbt Packages
● Utilizing git functionality within the development
lifecycle
● Creating Python models
● Providing access to users to models with the
“grants” configuration
Topic 2: Understanding dbt models governance
● Adding contracts to models to ensure the shape of
models
● Creating different versions of our models and
deprecating the old ones
● Configuring model access
Topic 3: Debugging data modeling errors
● Understanding logged error messages
● Troubleshooting using compiled code
● Troubleshooting .yml compilation errors
● Distinguishing between a pure SQL and a dbt issue
that presents itself as a SQL issue
● Developing and implementing a fix and testing it
prior to merging
Topic 4: Managing data pipelines
● Troubleshooting and managing failure points in
the DAG
● Using dbt clone
● Troubleshooting errors from integrated tools
Topic 5: Implementing dbt tests
● Using generic, singular, custom, and custom
generic tests on a wide variety of models and
sources
● Testing assumptions for dbt models and sources
● Implementing various testing steps in the workflow
Topic 6: Creating and Maintaining
dbt documentation
● Updating dbt docs
● Implementing source, table, and column
descriptions in .yml files
● Using macros to show model and data lineage on
the DAG
Topic 7: Implementing and maintaining
external dependencies
● Implementing dbt exposures
● Implementing source freshness
Topic 8: Leveraging the dbt state
● Understanding state
● Using dbt retry
● Combining state and result selectors
T
."""

context_data = """
---
SQL models
Related reference docs
Model configurations
Model properties
run command
ref function
Getting started
Building your first models
If you're new to dbt, we recommend that you read a quickstart guide to build your first dbt project with models.

dbt's Python capabilities are an extension of its capabilities with SQL models. If you're new to dbt, we recommend that you read this page first, before reading: "Python Models"

A SQL model is a select statement. Models are defined in .sql files (typically in your models directory):

Each .sql file contains one model / select statement
The model name is inherited from the filename and must match the filename of a model — including case sensitivity. Any mismatched casing can prevent dbt from applying configurations correctly and may affect metadata in Explorer.
We strongly recommend using underscores for model names, not dots. For example, use models/my_model.sql instead of models/my.model.sql.
Models can be nested in subdirectories within the models directory.
Refer to How we style our dbt models for details on how we recommend you name your models.

When you execute the dbt run command, dbt will build this model data warehouse by wrapping it in a create view as or create table as statement.

For example, consider this customers model:

models/customers.sql
with customer_orders as (
    select
        customer_id,
        min(order_date) as first_order_date,
        max(order_date) as most_recent_order_date,
        count(order_id) as number_of_orders

    from jaffle_shop.orders

    group by 1
)

select
    customers.customer_id,
    customers.first_name,
    customers.last_name,
    customer_orders.first_order_date,
    customer_orders.most_recent_order_date,
    coalesce(customer_orders.number_of_orders, 0) as number_of_orders

from jaffle_shop.customers

left join customer_orders using (customer_id)

When you execute dbt run, dbt will build this as a view named customers in your target schema:

create view dbt_alice.customers as (
    with customer_orders as (
        select
            customer_id,
            min(order_date) as first_order_date,
            max(order_date) as most_recent_order_date,
            count(order_id) as number_of_orders

        from jaffle_shop.orders

        group by 1
    )

    select
        customers.customer_id,
        customers.first_name,
        customers.last_name,
        customer_orders.first_order_date,
        customer_orders.most_recent_order_date,
        coalesce(customer_orders.number_of_orders, 0) as number_of_orders

    from jaffle_shop.customers

    left join customer_orders using (customer_id)
)

Why a view named dbt_alice.customers? By default dbt will:

Create models as views
Build models in a target schema you define
Use your file name as the view or table name in the database
You can use configurations to change any of these behaviors — more on that later.

FAQs
How can I see the SQL that dbt is running?
Do I need to create my target schema before running dbt?
If I rerun dbt, will there be any downtime as models are rebuilt?
What happens if the SQL in my query is bad or I get a database error?
Which SQL dialect should I write my models in? Or which SQL dialect does dbt use?
Configuring models
Configurations are "model settings" that you can set in your dbt_project.yml file, and in your model file using a config block. Some example configurations include:

Changing the materialization that a model uses — a materialization determines the SQL that dbt uses to create the model in your warehouse.
Build models into separate schemas.
Apply tags to a model.
The following diagram shows an example directory structure of a models folder:

models
├── staging
└── marts
    └── marketing

Here's an example of a model configuration:

dbt_project.yml
name: jaffle_shop
config-version: 2
...

models:
  jaffle_shop: # this matches the `name:`` config
    +materialized: view # this applies to all models in the current project
    marts:
      +materialized: table # this applies to all models in the `marts/` directory
      marketing:
        +schema: marketing # this applies to all models in the `marts/marketing/`` directory


models/customers.sql

{{ config(
    materialized="view",
    schema="marketing"
) }}

with customer_orders as ...


It is important to note that configurations are applied hierarchically — a configuration applied to a subdirectory will override any general configurations.

You can learn more about configurations in the reference docs.

FAQs
What materializations are available in dbt?
What model configurations exist?
Building dependencies between models
You can build dependencies between models by using the ref function in place of table names in a query. Use the name of another model as the argument for ref.

Model
Compiled code in dev
Compiled code in prod
models/customers.sql
with customers as (

    select * from {{ ref('stg_customers') }}

),

orders as (

    select * from {{ ref('stg_orders') }}

),

...


dbt uses the ref function to:

Determine the order to run the models by creating a dependent acyclic graph (DAG).
The DAG for our dbt project
The DAG for our dbt project
Manage separate environments — dbt will replace the model specified in the ref function with the database name for the table (or view). Importantly, this is environment-aware — if you're running dbt with a target schema named dbt_alice, it will select from an upstream table in the same schema. Check out the tabs above to see this in action.
Additionally, the ref function encourages you to write modular transformations, so that you can re-use models, and reduce repeated code.

Testing and documenting models
You can also document and test models — skip ahead to the section on testing and documentation for more information.


"""
# Use OllamaHandler's non-JSON mode since json_mode is False
result = OllamaHandler.invoke(
    agent_cfg,
    prompt_config,
    context_data,
    schema=None
)

# Print the first response since call_non_json returns a list
print(result[0])
