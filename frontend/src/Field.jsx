
import React, { useId, useState } from 'react';

import { limits, required } from './profile';

export default function Field({
  field,
  value,
  data,
  onChange,
  error,
}) {
  const id = useId();

  const [entry, setEntry] = useState('');

  const labelId = `${id}-label`;
  const helpId = `${id}-help`;
  const isRequired = required(field, data);

  let values = [];

  if (Array.isArray(value)) {
    values = value;
  }

  let inputValue = '';

  if (value !== null && value !== undefined) {
    inputValue = value;
  }

  let fieldClassName = 'field';

  if (field.full) {
    fieldClassName = 'field full';
  }

  let helpClassName = '';

  if (error) {
    helpClassName = 'error';
  }

  const helpText = error || field.help;

  const inputProps = {
    id,
    'aria-invalid': Boolean(error),
    'aria-describedby': helpId,
    value: inputValue,
    required: isRequired,
    onChange: handleTextChange,
  };

  function handleTextChange(event) {
    onChange(event.target.value);
  }

  function handleEntryChange(event) {
    setEntry(event.target.value);
  }

  function addEntry() {
    const trimmedEntry = entry.trim();

    if (trimmedEntry !== '') {
      const combinedValues = [...values, trimmedEntry];
      const uniqueValues = [...new Set(combinedValues)];

      onChange(uniqueValues);
    }

    setEntry('');
  }

  function handleEntryKeyDown(event) {
    if (event.key !== 'Enter') {
      return;
    }

    event.preventDefault();
    addEntry();
  }

  function handleChipClick(item) {
    if (field.type === 'choice') {
      onChange(item);

      return;
    }

    const isSelected = values.includes(item);

    if (isSelected) {
      const remainingValues = values.filter(function (selectedItem) {
        return selectedItem !== item;
      });

      onChange(remainingValues);

      return;
    }

    const updatedValues = [...values, item];

    onChange(updatedValues);
  }

  function renderChips() {
    let selectedItems = values;

    if (field.type === 'choice') {
      selectedItems = [value];
    }

    const nonEmptySelections = selectedItems.filter(Boolean);
    const combinedItems = [...field.options, ...nonEmptySelections];
    const availableItems = [...new Set(combinedItems)];
    const isEntryEmpty = entry.trim() === '';

    function renderChip(item) {
      const isSelected = selectedItems.includes(item);

      let className = 'chip';
      let removeSymbol = '';

      if (isSelected) {
        className = 'chip on';
      }

      if (field.type === 'tags' && isSelected) {
        removeSymbol = ' ×';
      }

      function handleClick() {
        handleChipClick(item);
      }

      return (
        <button
          key={item}
          type="button"
          className={className}
          aria-pressed={isSelected}
          onClick={handleClick}
        >
          {item}
          {removeSymbol}
        </button>
      );
    }

    return (
      <>
        <div
          className="chips"
          role="group"
          aria-labelledby={labelId}
        >
          {availableItems.map(renderChip)}
        </div>

        {field.type === 'tags' && (
          <div className="tag-entry">
            <input
              id={id}
              value={entry}
              maxLength={300}
              placeholder="Type a value and add"
              onChange={handleEntryChange}
              onKeyDown={handleEntryKeyDown}
            />

            <button
              type="button"
              className="btn"
              onClick={addEntry}
              disabled={isEntryEmpty}
            >
              Add
            </button>
          </div>
        )}
      </>
    );
  }

  function renderOption(option) {
    return (
      <option key={option}>
        {option}
      </option>
    );
  }

  function renderSelect() {
    return (
      <select {...inputProps}>
        <option value="">Choose an option</option>

        {field.options.map(renderOption)}
      </select>
    );
  }

  function handleTextareaChange(event) {
    const text = event.target.value;

    if (field.type === 'lines') {
      const lines = text.split('\n');

      onChange(lines);

      return;
    }

    onChange(text);
  }

  function renderTextarea() {
    let text = inputValue;

    if (field.type === 'lines') {
      text = values.join('\n');
    }

    return (
      <textarea
        {...inputProps}
        maxLength={10000}
        value={text}
        onChange={handleTextareaChange}
      />
    );
  }

  function handleInputChange(event) {
    const newValue = event.target.value;

    if (field.type === 'number' && newValue !== '') {
      const numberValue = Number(newValue);

      onChange(numberValue);

      return;
    }

    onChange(newValue);
  }

  function renderInput() {
    const fieldLimits = limits[field.key] || [];
    const [min, max] = fieldLimits;

    let inputType = 'text';
    let placeholder = '';

    if (field.type === 'number') {
      inputType = 'number';
    }

    if (field.key === 'word_range') {
      placeholder = '100-200';
    }

    return (
      <input
        {...inputProps}
        type={inputType}
        min={min}
        max={max}
        maxLength={10000}
        placeholder={placeholder}
        onChange={handleInputChange}
      />
    );
  }

  function renderControl() {
    const chipTypes = ['tags', 'multi', 'choice'];

    if (chipTypes.includes(field.type)) {
      return renderChips();
    }

    if (field.type === 'select') {
      return renderSelect();
    }

    if (field.type === 'area' || field.type === 'lines') {
      return renderTextarea();
    }

    return renderInput();
  }

  function renderRequiredLabel() {
    if (isRequired) {
      return (
        <span className="required">*</span>
      );
    }

    return (
      <span className="optional">Optional</span>
    );
  }

  return (
    <div className={fieldClassName}>
      <label id={labelId} htmlFor={id}>
        {field.label}{' '}
        {renderRequiredLabel()}
      </label>

      {renderControl()}

      <small id={helpId} className={helpClassName}>
        {helpText}
      </small>
    </div>
  );
}