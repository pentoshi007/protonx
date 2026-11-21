package dev.pentoshi.protonx.ui

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import dev.pentoshi.protonx.R
import dev.pentoshi.protonx.core.CountryNames
import dev.pentoshi.protonx.core.CountryRow
import dev.pentoshi.protonx.core.Logical
import dev.pentoshi.protonx.databinding.ItemCountryBinding
import dev.pentoshi.protonx.databinding.ItemServerBinding

class CountryAdapter(private val onClick: (CountryRow) -> Unit) : RecyclerView.Adapter<CountryAdapter.Holder>() {
    private val items = mutableListOf<CountryRow>()

    fun submit(rows: List<CountryRow>) {
        items.clear()
        items.addAll(rows)
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder =
        Holder(ItemCountryBinding.inflate(LayoutInflater.from(parent.context), parent, false))

    override fun getItemCount(): Int = items.size

    override fun onBindViewHolder(holder: Holder, position: Int) = holder.bind(items[position])

    inner class Holder(private val binding: ItemCountryBinding) : RecyclerView.ViewHolder(binding.root) {
        fun bind(row: CountryRow) {
            binding.countryCode.text = row.code
            binding.countryName.text = row.name
            binding.countryDetail.text = binding.root.context.getString(R.string.server_count, row.servers)
            binding.countryLoad.text = binding.root.context.getString(R.string.server_load, row.bestLoad)
            binding.root.setOnClickListener { onClick(row) }
        }
    }
}

class ServerAdapter(
    private val active: () -> String?,
    private val onClick: (Logical) -> Unit,
) : RecyclerView.Adapter<ServerAdapter.Holder>() {
    private val items = mutableListOf<Logical>()

    fun submit(rows: List<Logical>) {
        items.clear()
        items.addAll(rows)
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder =
        Holder(ItemServerBinding.inflate(LayoutInflater.from(parent.context), parent, false))

    override fun getItemCount(): Int = items.size

    override fun onBindViewHolder(holder: Holder, position: Int) = holder.bind(items[position])

    inner class Holder(private val binding: ItemServerBinding) : RecyclerView.ViewHolder(binding.root) {
        fun bind(logical: Logical) {
            val context = binding.root.context
            binding.serverName.text = logical.displayName()
            val city = logical.city.ifBlank { CountryNames.of(logical.exitCountry) }
            binding.serverDetail.text = "$city · ${context.getString(R.string.server_load, logical.load)}"
            binding.serverActive.visibility =
                if (active() == logical.displayName()) android.view.View.VISIBLE else android.view.View.GONE
            binding.root.setOnClickListener { onClick(logical) }
        }
    }
}
